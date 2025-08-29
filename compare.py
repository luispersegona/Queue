import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
import asyncio
import logging
import io
from PIL import Image, ImageDraw, ImageFont
from typing import Optional, Dict, Any
import itertools  # Adicione esta importação

from defi.checks import is_rank_channel_check

# Configurar logger
logger = logging.getLogger(__name__)

# PUBG API Configs (Ajuste para sua plataforma, se necessário)
PUBG_API_BASE_URL = "https://api.pubg.com/shards/steam"

# Variáveis de cache globais
current_season_id_cache = None
player_id_cache = {}

# Nova classe para gerenciar a rotação de chaves da API
class ApiKeyManager:
    def __init__(self, key_prefix: str = "PUBG_API_KEY"):
        """
        Inicializa o gerenciador de chaves de API.
        Busca todas as chaves do ambiente com o prefixo especificado.
        """
        self.keys = []
        for key, value in os.environ.items():
            if key.startswith(key_prefix) and value:
                self.keys.append(value)
        
        if not self.keys:
            raise ValueError("Nenhuma chave de API encontrada com o prefixo fornecido.")
            
        # Usa um iterador cíclico para alternar entre as chaves
        self.key_iterator = itertools.cycle(self.keys)
        
    def get_next_key(self) -> str:
        """
        Retorna a próxima chave de API na sequência.
        """
        return next(self.key_iterator)


# Funções de busca da API (agora recebem a chave como argumento)
async def get_current_season_id(session: aiohttp.ClientSession, headers: dict) -> str | None:
    """Busca o ID da temporada atual da API, com cache global."""
    global current_season_id_cache
    if current_season_id_cache:
        return current_season_id_cache

    seasons_url = f"{PUBG_API_BASE_URL}/seasons"
    try:
        async with session.get(seasons_url, headers=headers) as response:
            response.raise_for_status()
            seasons_data = await response.json()
            current_season = next((s for s in seasons_data.get("data", []) if s.get("attributes", {}).get("isCurrentSeason")), None)
            if current_season:
                current_season_id_cache = current_season.get("id")
                return current_season_id_cache
    except Exception as e:
        logger.error(f"Erro ao buscar ID da temporada: {e}")
        return None

async def get_player_id(session: aiohttp.ClientSession, headers: dict, player_name: str) -> str | None:
    """Busca o Account ID de um jogador, com cache global."""
    global player_id_cache
    if player_name in player_id_cache:
        return player_id_cache[player_name]

    player_url = f"{PUBG_API_BASE_URL}/players?filter[playerNames]={player_name}"
    try:
        async with session.get(player_url, headers=headers) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            player_data = await response.json()
            if not player_data or not player_data.get("data"):
                return None
            account_id = player_data["data"][0]["id"]
            player_id_cache[player_name] = account_id
            return account_id
    except Exception as e:
        logger.error(f"Erro ao buscar Account ID para '{player_name}': {e}")
        return None

async def fetch_player_rank_stats(session: aiohttp.ClientSession, pubg_api_key: str, player_name: str) -> Optional[Dict[str, Any]]:
    """Busca e processa as estatísticas de rank de um jogador."""
    headers = {
        "Authorization": f"Bearer {pubg_api_key}",
        "Accept": "application/vnd.api+json"
    }
    account_id = await get_player_id(session, headers, player_name)
    if not account_id:
        return None
    season_id = await get_current_season_id(session, headers)
    if not season_id:
        return None
    try:
        stats_url = f"{PUBG_API_BASE_URL}/players/{account_id}/seasons/{season_id}/ranked"
        async with session.get(stats_url, headers=headers) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            data = await response.json()
        ranked_stats = data.get("data", {}).get("attributes", {}).get("rankedGameModeStats", {}).get("squad-fpp")
        if not ranked_stats:
            return None
        tier_info = ranked_stats.get("currentTier", {"tier": "Unranked", "subTier": ""})
        rank_str = f"{tier_info.get('tier')} {tier_info.get('subTier')}".strip()
        return {
            "nickname": player_name,
            "rank": rank_str,
            "points": ranked_stats.get("currentRankPoint", 0),
            "wins": ranked_stats.get("wins", 0),
            "kda": ranked_stats.get("kda", 0),
        }
    except Exception as e:
        logger.error(f"Erro ao buscar estatísticas de rank para '{player_name}': {e}")
        return None

async def fetch_player_match_stats(session: aiohttp.ClientSession, pubg_api_key: str, player_name: str, match_count: int) -> Optional[Dict[str, Any]]:
    """Busca as estatísticas médias das últimas partidas de um jogador."""
    headers = {
        "Authorization": f"Bearer {pubg_api_key}",
        "Accept": "application/vnd.api+json"
    }
    try:
        player_url = f"{PUBG_API_BASE_URL}/players?filter[playerNames]={player_name}"
        async with session.get(player_url, headers=headers) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            data = await response.json()
            if not data.get("data"):
                return None
            player_data = data["data"][0]
            match_ids = [match.get("id") for match in player_data.get("relationships", {}).get("matches", {}).get("data", []) if match.get("id")][:match_count]
            if not match_ids:
                return {"nickname": player_name, "avg_damage": 0, "avg_kills": 0, "avg_assists": 0, "num_matches": 0}
        
        fetch_tasks = [fetch_match_data(session, pubg_api_key, match_id) for match_id in match_ids]
        match_data_list = await asyncio.gather(*fetch_tasks)
        dados_performance = []
        for match_data in match_data_list:
            if match_data:
                stats = extract_player_stats_from_match(match_data, player_name)
                if stats:
                    dados_performance.append(stats)
        if not dados_performance:
            return {"nickname": player_name, "avg_damage": 0, "avg_kills": 0, "avg_assists": 0, "num_matches": 0}
            
        dano_total = sum(d['dano'] for d in dados_performance)
        kills_total = sum(d['kills'] for d in dados_performance)
        assists_total = sum(d['assists'] for d in dados_performance)
        num_partidas = len(dados_performance)
        
        return {
            "nickname": player_name,
            "avg_damage": dano_total / num_partidas,
            "avg_kills": kills_total / num_partidas,
            "avg_assists": assists_total / num_partidas,
            "num_matches": num_partidas
        }
    except Exception as e:
        logger.error(f"Erro ao buscar estatísticas de partidas para '{player_name}': {e}")
        return None

async def fetch_match_data(session: aiohttp.ClientSession, pubg_api_key: str, match_id: str) -> Optional[Dict[str, Any]]:
    """Busca dados de uma única partida."""
    headers = {
        "Authorization": f"Bearer {pubg_api_key}",
        "Accept": "application/vnd.api+json"
    }
    url = f"{PUBG_API_BASE_URL}/matches/{match_id}"
    try:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        logger.error(f"Erro buscando dados da partida {match_id}: {e}")
        return None

def extract_player_stats_from_match(match_data: Dict[str, Any], nickname: str) -> Optional[Dict[str, float | int]]:
    """Extrai as estatísticas do jogador dos dados da partida."""
    if not match_data or "included" not in match_data:
        return None
    for item in match_data.get("included", []):
        if item.get("type") == "participant":
            stats = item.get("attributes", {}).get("stats", {})
            if stats.get("name", "").lower() == nickname.lower():
                return {
                    "dano": stats.get("damageDealt", 0.0),
                    "kills": stats.get("kills", 0),
                    "assists": stats.get("assists", 0),
                }
    return None

class PUBGCompare(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if not hasattr(bot, 'http_session') or bot.http_session is None:
            logger.critical("aiohttp.ClientSession não foi inicializada no bot! PUBGCompare Cog não pode ser carregada corretamente.")
            raise RuntimeError("aiohttp.ClientSession não inicializada. Verifique a ordem de carregamento ou o main.py.")
        
        try:
            # Inicializa o gerenciador de chaves da API
            self.api_key_manager = ApiKeyManager()
            logger.info("PUBG API Key Manager inicializado com sucesso.")
        except ValueError as e:
            self.api_key_manager = None
            logger.error(f"Erro ao inicializar o gerenciador de chaves da API do PUBG: {e}")

    @app_commands.command(name='versus', description='Compara as estatísticas de rank e partidas recentes de dois jogadores de PUBG.')
    @is_rank_channel_check
    @app_commands.describe(
        player1="Nome do primeiro jogador PUBG",
        player2="Nome do segundo jogador PUBG",
        partidas="Número de partidas recentes para comparar as médias (padrão: 5)"
    )
    async def compare(self, interaction: discord.Interaction, player1: str, player2: str, partidas: Optional[int] = 5):
        logger.info(f"Comando compare executado por {interaction.user} para jogadores '{player1}' e '{player2}' (com {partidas} partidas).")
        
        if not self.api_key_manager:
            await interaction.response.send_message("❌ Erro interno: O gerenciador de chaves da API do PUBG não está configurado.", ephemeral=True)
            return
        
        if partidas <= 0 or partidas > 10:
            await interaction.response.send_message("❌ O número de partidas deve ser entre 1 e 10.", ephemeral=True)
            return

        session = self.bot.http_session
        
        # Obtém a próxima chave da fila para esta requisição
        api_key_for_this_request = self.api_key_manager.get_next_key()
        
        # Busca as estatísticas de ambos os jogadores em paralelo antes do defer
        rank_stats1, match_stats1 = await asyncio.gather(
            fetch_player_rank_stats(session, api_key_for_this_request, player1),
            fetch_player_match_stats(session, api_key_for_this_request, player1, partidas)
        )
        rank_stats2, match_stats2 = await asyncio.gather(
            fetch_player_rank_stats(session, api_key_for_this_request, player2),
            fetch_player_match_stats(session, api_key_for_this_request, player2, partidas)
        )

        # Bloco de tratamento de erro para jogadores não encontrados
        if not rank_stats1 and not rank_stats2:
            await interaction.response.send_message(f"❌ Não foi possível encontrar dados para os jogadores **{player1}** e **{player2}**.", ephemeral=True)
            return
        elif not rank_stats1:
            await interaction.response.send_message(f"❌ Não foi possível encontrar dados para o jogador **{player1}**.", ephemeral=True)
            return
        elif not rank_stats2:
            await interaction.response.send_message(f"❌ Não foi possível encontrar dados para o jogador **{player2}**.", ephemeral=True)
            return

        # Se não houver erros, faça o defer público
        await interaction.response.defer(ephemeral=False)

        try:
            # Define os caminhos dos arquivos com base na nova estrutura de pastas
            base_dir = os.path.dirname(os.path.dirname(__file__))
            image_path = os.path.join(base_dir, 'compare', 'compare.png')
            font_path = os.path.join(base_dir, 'fonts', 'pubgsans.ttf')
            
            # Verificação de arquivos para depuração
            if not os.path.exists(image_path):
                print(f"ERRO: A imagem não foi encontrada no caminho: {image_path}")
                await interaction.followup.send("❌ Erro interno: A imagem de fundo não foi encontrada. Verifique o arquivo e o caminho.", ephemeral=True)
                return

            if not os.path.exists(font_path):
                print(f"ERRO: A fonte não foi encontrada no caminho: {font_path}")
                await interaction.followup.send("❌ Erro interno: A fonte não foi encontrada. Verifique o arquivo e o caminho.", ephemeral=True)
                return

            # Combina as estatísticas
            stats1 = {**rank_stats1, **match_stats1}
            stats2 = {**rank_stats2, **match_stats2}
            
            # Carrega a imagem e cria o objeto de desenho
            img = Image.open(image_path).convert("RGBA")
            draw = ImageDraw.Draw(img)

            # Carrega as fontes.
            try:
                font_title = ImageFont.truetype(font_path, 100)
                font_stats = ImageFont.truetype(font_path, 50)
            except IOError:
                logger.warning("Fonte não encontrada, usando a fonte padrão.")
                font_title = ImageFont.load_default()
                font_stats = ImageFont.load_default()

            # Adicionando os ícones de seta
            up_arrow_path = os.path.join(base_dir, 'icons', 'up.png')
            down_arrow_path = os.path.join(base_dir, 'icons', 'down.png')
            
            # Verificação de arquivos de ícones
            if not os.path.exists(up_arrow_path) or not os.path.exists(down_arrow_path):
                print("ERRO: Um ou ambos os arquivos de ícone de seta não foram encontrados.")
                up_arrow_img = None
                down_arrow_img = None
            else:
                up_arrow_img = Image.open(up_arrow_path).convert("RGBA")
                down_arrow_img = Image.open(down_arrow_path).convert("RGBA")
                
                # Redimensiona os ícones para um tamanho adequado (ex: 70x70)
                icon_size = (70, 70)
                up_arrow_img = up_arrow_img.resize(icon_size)
                down_arrow_img = down_arrow_img.resize(icon_size)

            # Posições para os jogadores
            img_width, _ = img.size
            x1_pos = img_width * 0.12
            x2_pos = img_width * 0.69

            # Função auxiliar para desenhar o texto e os ícones
            def draw_player_stats(stats_dict, other_stats_dict, x_start):
                 # Adiciona um check para garantir que os dicionários não são None
                 if not stats_dict:
                     return

                 y_pos = 100
                 draw.text((x_start, y_pos), stats_dict.get('nickname', ''), font=font_title, fill=(255, 165, 0))
                 y_pos += 230

                 # RANK
                 draw.text((x_start, y_pos), "RANK", font=font_stats, fill=(255, 255, 255))
                 draw.text((x_start, y_pos + 45), f"{stats_dict.get('rank', 'N/A')}", font=font_stats, fill=(255, 165, 0))
                 y_pos += 100
                 
                 # PONTOS
                 draw.text((x_start, y_pos), "PONTOS", font=font_stats, fill=(255, 255, 255))
                 draw.text((x_start, y_pos + 45), f"{stats_dict.get('points', 0):,}", font=font_stats, fill=(255, 165, 0))
                 y_pos += 100
                 
                 # KDA
                 draw.text((x_start, y_pos), "KDA", font=font_stats, fill=(255, 255, 255))
                 draw.text((x_start, y_pos + 45), f"{stats_dict.get('kda', 0):.2f}", font=font_stats, fill=(255, 165, 0))
                 y_pos += 100

                 # VITÓRIAS
                 draw.text((x_start, y_pos), "VITÓRIAS", font=font_stats, fill=(255, 255, 255))
                 draw.text((x_start, y_pos + 45), f"{stats_dict.get('wins', 'N/A')}", font=font_stats, fill=(255, 165, 0))
                 y_pos += 100
                 
                 # MÉDIAS
                 draw.text((x_start, y_pos), f"MÉDIA ÚLTIMAS:", font=font_stats, fill=(255, 255, 255))
                 media_text_width = draw.textlength("MÉDIA ÚLTIMAS:", font=font_stats)
                 draw.text((x_start + media_text_width + 5, y_pos), f"{partidas}", font=font_stats, fill=(255, 165, 0))
                 y_pos += 70

                 # DANO
                 dano_text_width = draw.textlength("DANO:", font=font_stats)
                 draw.text((x_start, y_pos), "DANO:", font=font_stats, fill=(255, 255, 255))
                 draw.text((x_start + dano_text_width + 5, y_pos), f"{stats_dict.get('avg_damage', 0):.1f}", font=font_stats, fill=(255, 165, 0))
                 if up_arrow_img and stats_dict.get('avg_damage') is not None and other_stats_dict is not None and other_stats_dict.get('avg_damage') is not None:
                     if stats_dict.get('avg_damage') > other_stats_dict.get('avg_damage'):
                         img.paste(up_arrow_img, (int(x_start + dano_text_width + 200), int(y_pos)), up_arrow_img)
                     elif stats_dict.get('avg_damage') < other_stats_dict.get('avg_damage'):
                         img.paste(down_arrow_img, (int(x_start + dano_text_width + 200), int(y_pos)), down_arrow_img)
                 y_pos += 70

                 # KILLS
                 kills_text_width = draw.textlength("KILLS:", font=font_stats)
                 draw.text((x_start, y_pos), "KILLS:", font=font_stats, fill=(255, 255, 255))
                 draw.text((x_start + kills_text_width + 5, y_pos), f"{stats_dict.get('avg_kills', 0):.1f}", font=font_stats, fill=(255, 165, 0))
                 if up_arrow_img and stats_dict.get('avg_kills') is not None and other_stats_dict is not None and other_stats_dict.get('avg_kills') is not None:
                     if stats_dict.get('avg_kills') > other_stats_dict.get('avg_kills'):
                         img.paste(up_arrow_img, (int(x_start + kills_text_width + 200), int(y_pos)), up_arrow_img)
                     elif stats_dict.get('avg_kills') < other_stats_dict.get('avg_kills'):
                         img.paste(down_arrow_img, (int(x_start + kills_text_width + 200), int(y_pos)), down_arrow_img)
                 y_pos += 70

                 # ASSISTS
                 assists_text_width = draw.textlength("ASSISTS:", font=font_stats)
                 draw.text((x_start, y_pos), "ASSISTS:", font=font_stats, fill=(255, 255, 255))
                 draw.text((x_start + assists_text_width + 5, y_pos), f"{stats_dict.get('avg_assists', 0):.1f}", font=font_stats, fill=(255, 165, 0))
                 if up_arrow_img and stats_dict.get('avg_assists') is not None and other_stats_dict is not None and other_stats_dict.get('avg_assists') is not None:
                     if stats_dict.get('avg_assists') > other_stats_dict.get('avg_assists'):
                         img.paste(up_arrow_img, (int(x_start + assists_text_width + 200), int(y_pos)), up_arrow_img)
                     elif stats_dict.get('avg_assists') < other_stats_dict.get('avg_assists'):
                         img.paste(down_arrow_img, (int(x_start + assists_text_width + 200), int(y_pos)), down_arrow_img)
            
            # Desenha as estatísticas para ambos os jogadores
            draw_player_stats(stats1, stats2, x1_pos)
            draw_player_stats(stats2, stats1, x2_pos)

            # Salva a imagem em um buffer de memória
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="PNG")
            img_buffer.seek(0)

            # Cria e envia o arquivo no Discord
            discord_file = discord.File(img_buffer, filename="compare_pubg.png")
            await interaction.followup.send(file=discord_file)

        except Exception as e:
            logger.error(f"Erro inesperado no comando compare: {e}", exc_info=True)
            # Como a interação já foi deferida publicamente, este erro também será público
            await interaction.followup.send("❌ Ocorreu um erro inesperado. Tente novamente mais tarde.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PUBGCompare(bot))
    logger.info("Cog 'PUBGCompare' carregada com sucesso.")