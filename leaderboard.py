import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
import datetime
import pytz
import json
import os
import logging
import re
from itertools import cycle
from collections import defaultdict

# IMPORTAÇÃO DO MÓDULO DE RATE LIMITER (Assumindo que está no mesmo local)
from defi.rate_limiter import AsyncRateLimiter
from defi.checks import is_rank_channel_check

# Importação da biblioteca Pillow
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io

logger = logging.getLogger(__name__)

class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        self.pubg_api_keys_with_names = [] 
        main_key_value = os.getenv('PUBG_API_KEY')
        if main_key_value:
            self.pubg_api_keys_with_names.append(('PUBG_API_KEY', main_key_value))
        
        for i in range(1, 10): 
            key_name = f'PUBG_API_KEY{i}'
            key_value = os.getenv(key_name)
            if key_value:
                self.pubg_api_keys_with_names.append((key_name, key_value))
            else:
                break
        
        if not self.pubg_api_keys_with_names:
            logger.critical("ERRO: Nenhuma PUBG API Key encontrada. A cog Leaderboard não funcionará.")
            self.current_api_key_iterator = None
            self.pubg_api_key = None
            self.pubg_api_key_name = None
            self.api_key_limiters = {} 
        else:
            self.current_api_key_iterator = cycle(self.pubg_api_keys_with_names)
            self.pubg_api_key_name, self.pubg_api_key = next(self.current_api_key_iterator) 
            logger.info(f"Carregadas {len(self.pubg_api_keys_with_names)} chaves de API do PUBG para Leaderboard. Iniciando com {self.pubg_api_key_name}.")
            
            self.api_key_limiters = {
                key_value: AsyncRateLimiter(rate=10, per_second=60)
                for key_name, key_value in self.pubg_api_keys_with_names
            }
            self.active_api_rate_limiter = self.api_key_limiters[self.pubg_api_key]
            logger.info(f"Inicializados {len(self.api_key_limiters)} limitadores de taxa, um para cada chave para Leaderboard.")

        self.base_url = "https://api.pubg.com/shards/steam"
        
        self.headers = {
            "Authorization": f"Bearer {self.pubg_api_key}",
            "Accept": "application/vnd.api+json"
        }
        
        self.json_file_path = 'leaderboard_pubg_sa.json'
        
        self.all_tiers = ["Survivor", "Master", "Diamond", "Crystal", "Platinum", "Gold", "Silver", "Bronze"] 

        self.LEADERBOARD_IMAGES = {
            "Bronze": "https://i.postimg.cc/34tLzRSm/bronze1-removebg-preview.png",
            "Silver": "https://i.postimg.cc/JHBbK491/prata1-removebg-preview.png",
            "Gold": "https://i.postimg.cc/jw3XZ12h/ouro1-removebg-preview.png",
            "Platinum": "https://i.postimg.cc/G4PxZt9t/platina1-removebg-preview.png",
            "Crystal": "https://i.postimg.cc/bJs8tpzf/Chat-GPT-Image-8-de-jun-de-2025-09-08-52.png",
            "Diamond": "https://i.postimg.cc/dLb5bgBH/dima1-removebg-preview.png",
            "Master": "https://i.postimg.cc/NLLb5QCC/mestre-removebg-preview.png",
            "Survivor": "https://i.postimg.cc/s2nsxvCJ/survivor-medal-transparent.png",
        }
        
        self.background_image_path = 'compare/leaderboard.png'
        self.font_path = 'fonts/pubgsans.ttf'

        try:
            self.pubg_font_regular = ImageFont.truetype(self.font_path, 40)
            self.pubg_font_small = ImageFont.truetype(self.font_path, 25)
            logger.info(f"Fonte carregada com sucesso: {self.font_path}")
        except IOError:
            logger.critical(f"ERRO: Não foi possível carregar a fonte em '{self.font_path}'. Certifique-se de que o arquivo existe.")
            self.pubg_font_regular = ImageFont.load_default()
            self.pubg_font_small = ImageFont.load_default()
        
    async def cog_load(self):
        if self.pubg_api_keys_with_names:
            logger.info("Leaderboard Cog: Iniciando loops de atualização.")
            self.hourly_leaderboard_update.start()
        else:
            logger.critical("Leaderboard Cog não iniciado devido à falta de PUBG API Keys.")

    async def cog_unload(self):
        logger.info("Leaderboard Cog: Cancelando loops de atualização.")
        self.daily_leaderboard_update.cancel()
        self.hourly_leaderboard_update.cancel()

    async def _update_api_key_and_headers(self):
        """Atualiza a chave da API e o limitador de taxa ativo."""
        if self.current_api_key_iterator:
            self.pubg_api_key_name, self.pubg_api_key = next(self.current_api_key_iterator)
            self.headers["Authorization"] = f"Bearer {self.pubg_api_key}"
            self.active_api_rate_limiter = self.api_key_limiters[self.pubg_api_key]
            logger.debug(f"Usando PUBG API Key para Leaderboard: {self.pubg_api_key_name}")
        else:
            logger.error("Tentativa de atualizar a API Key para Leaderboard sem um iterador de chaves válido.")
            self.headers["Authorization"] = "Bearer INVALID_KEY" 
            self.active_api_rate_limiter = None 
            self.pubg_api_key_name = "N/A"

    @tasks.loop(hours=24)
    async def daily_leaderboard_update(self):
        now = datetime.datetime.now(pytz.timezone('America/Sao_Paulo'))
        logger.info(f"Iniciando atualização diária do leaderboard às {now.strftime('%H:%M:%S')}")
        
        await self.fetch_and_save_leaderboard_json(self.bot.http_session)
        logger.info("Atualização diária do leaderboard concluída.")

    @daily_leaderboard_update.before_loop
    async def before_daily_leaderboard_update(self):
        await self.bot.wait_until_ready()
        
        logger.info("Leaderboard Cog: Executando busca inicial do leaderboard na inicialização do bot.")
        await self.fetch_and_save_leaderboard_json(self.bot.http_session)
        logger.info("Leaderboard Cog: Busca inicial do leaderboard concluída.")

        now = datetime.datetime.now(pytz.timezone('America/Sao_Paulo'))
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
        if now >= next_run:
            next_run += datetime.timedelta(days=1)
        time_to_wait = (next_run - now).total_seconds()
        logger.info(f"Leaderboard Cog: Agendando a próxima execução diária do loop para {next_run.strftime('%Y-%m-%d %H:%M:%S')} (esperando {time_to_wait:.2f} segundos).")
        await asyncio.sleep(time_to_wait)

    @tasks.loop(hours=1)
    async def hourly_leaderboard_update(self):
        now = datetime.datetime.now(pytz.timezone('America/Sao_Paulo'))
        logger.info(f"Iniciando atualização horária do leaderboard às {now.strftime('%H:%M:%S')}")
        
        await self.fetch_and_save_leaderboard_json(self.bot.http_session)
        logger.info("Atualização horária do leaderboard concluída.")

    @hourly_leaderboard_update.before_loop
    async def before_hourly_leaderboard_update(self):
        await self.bot.wait_until_ready()
        logger.info("Leaderboard Cog: Loop de atualização horária pronto para iniciar.")

    async def fetch_and_save_leaderboard_json(self, session, expected_season_number: int = None):
        if not self.pubg_api_key or self.active_api_rate_limiter is None:
            logger.error("Não há PUBG API Key ativa ou limitador de taxa para buscar o leaderboard completo.")
            return False

        logger.info(f"Iniciando busca do leaderboard completo para salvamento em JSON.")

        if session is None or session.closed:
            logger.error("aiohttp session não disponível ou fechada para busca de leaderboard completo.")
            return False

        try:
            leaderboard_base_url = "https://api.pubg.com/shards/pc-sa" 
            
            await self._update_api_key_and_headers()
            
            async with self.active_api_rate_limiter:
                current_season_id = await self.get_current_season(session, leaderboard_base_url, expected_season_number)
            
            await asyncio.sleep(1)

            if not current_season_id:
                logger.error("Não foi possível encontrar NENHUMA temporada ranqueada ativa para buscar o leaderboard completo.")
                return False

            season_number_match = re.search(r'(\d+)$', current_season_id)
            season_display_number = season_number_match.group(1) if season_number_match else "Desconhecida"

            leaderboard_modes = ['squad-fpp']
            
            all_leaderboard_data = {}

            for modo_value in leaderboard_modes:
                leaderboard_url = f"{leaderboard_base_url}/leaderboards/{current_season_id}/{modo_value}"
                logger.info(f"Buscando leaderboard completo para modo {modo_value}...")

                await self._update_api_key_and_headers()
                
                async with self.active_api_rate_limiter:
                    async with session.get(leaderboard_url, headers=self.headers) as response:
                        if response.status == 200:
                            leaderboard_data = await response.json()
                            all_leaderboard_data[modo_value] = leaderboard_data
                            logger.info(f"Resposta completa do leaderboard para modo {modo_value} obtida (Temporada: {season_display_number}).")
                        elif response.status == 429:
                            retry_after = int(response.headers.get('Retry-After', 30))
                            logger.warning(f"Rate limit atingido ao buscar leaderboard completo para modo {modo_value} (KEY: {self.pubg_api_key_name}). Esperando {retry_after}s. Isso pode atrasar o processo.")
                            await asyncio.sleep(retry_after + 1)
                            continue 
                        else:
                            logger.error(f"Erro ao acessar o leaderboard completo para modo {modo_value}: Status {response.status} - {await response.text()} (KEY: {self.pubg_api_key_name}).")
                
                await asyncio.sleep(1)

        except aiohttp.ClientError as e:
            logger.error(f"Erro de conexão ao tentar buscar o leaderboard completo: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Ocorreu um erro inesperado durante a busca de dados do leaderboard completo: {type(e).__name__} - {e}", exc_info=True)
            return False

        try:
            with open(self.json_file_path, 'w', encoding='utf-8') as jsonfile:
                json.dump(all_leaderboard_data, jsonfile, ensure_ascii=False, indent=4)
            logger.info(f"Dados completos do leaderboard salvos em '{self.json_file_path}'.")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar os dados completos do leaderboard no arquivo JSON: {e}", exc_info=True)
            return False

    async def get_current_season(self, session, base_url: str, expected_season_number: int = None):
        if not self.pubg_api_key or self.active_api_rate_limiter is None:
            logger.error("Não há PUBG API Key ativa ou limitador de taxa para obter a temporada atual (Leaderboard Cog).")
            return None

        logger.debug(f"Tentando obter temporada ranqueada atual (KEY: {self.pubg_api_key_name}). Número esperado: {expected_season_number}")
        try:
            seasons_url = f"{base_url}/seasons"
            
            async with self.active_api_rate_limiter: 
                async with session.get(seasons_url, headers=self.headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        all_seasons = data.get('data', [])
                        
                        if not all_seasons:
                            logger.warning("Nenhuma temporada encontrada na API do PUBG (Leaderboard Cog).")
                            return None

                        for season in all_seasons:
                            if season.get('attributes', {}).get('isCurrentSeason') is True:
                                season_id = season['id']
                                if re.search(r'division\.bro\.official\.pc-2018-\d+', season_id):
                                    logger.info(f"Encontrada temporada atual (isCurrentSeason=True) para Leaderboard: {season_id}")
                                    return season_id
                                else:
                                    logger.warning(f"Temporada atual '{season_id}' encontrada, mas com formato de ID inesperado para ranqueada. Ignorando (Leaderboard Cog).")

                        if expected_season_number:
                            for season in all_seasons:
                                season_id = season['id']
                                match = re.search(r'division\.bro\.official\.pc-2018-(\d+)', season_id)
                                if match and int(match.group(1)) == expected_season_number:
                                    logger.info(f"Encontrada temporada ranqueada esperada para Leaderboard: {season_id} (Número: {expected_season_number})")
                                    return season_id

                        ranked_like_seasons = []
                        for season in all_seasons:
                            season_id = season['id']
                            if re.search(r'division\.bro\.official\.pc-2018-\d+', season_id):
                                ranked_like_seasons.append(season)

                        if ranked_like_seasons:
                            ranked_like_seasons.sort(key=lambda s: int(re.search(r'(\d+)$', s['id']).group(1)) if re.search(r'(\d+)$', s['id']) else 0, reverse=True)
                            most_recent_season_id = ranked_like_seasons[0]['id']
                            logger.info(f"Retornando temporada ranqueada mais recente por padrão de ID para Leaderboard: {most_recent_season_id}")
                            return most_recent_season_id

                        logger.warning("Nenhuma temporada ranqueada ativa ou com padrão reconhecido encontrada na API do PUBG (Leaderboard Cog).")
                        return None
                    else:
                        logger.error(f"Erro ao obter temporadas da API do PUBG para Leaderboard: Status {response.status} - {await response.text()} (KEY: {self.pubg_api_key_name}).")
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"Erro de conexão com a API do PUBG (get_current_season no Leaderboard Cog): {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Exceção inesperada em get_current_season (Leaderboard Cog): {e}", exc_info=True)
            return None

    def _draw_text_with_options(self, draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font_size: int, color: tuple, centered: bool = False):
        """
        Função auxiliar para desenhar texto com opções de cor, tamanho e centralização.
        """
        try:
            font = ImageFont.truetype(self.font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            logger.warning(f"Fonte não encontrada, usando fonte padrão.")

        if centered:
            # Calcula a caixa delimitadora do texto para centralizar
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            x_pos = x - (text_width / 2)
        else:
            x_pos = x

        draw.text((x_pos, y), text, font=font, fill=color)

    async def generate_leaderboard_image(self, selected_tier: str, top_players: list, last_updated: str) -> io.BytesIO:
        """
        Gera a imagem do leaderboard com os jogadores e informações.
        Retorna um io.BytesIO contendo a imagem.
        """
        try:
            background = Image.open(self.background_image_path).convert("RGBA")
            draw = ImageDraw.Draw(background)

            # =================================================================
            # === AJUSTES DE CONFIGURAÇÃO DE TEXTO E POSICIONAMENTO AQUI ===
            # =================================================================
            
            # --- Configurações do Título ---
            title_text = f"{selected_tier}"
            title_x, title_y = background.width // 2, 100
            title_font_size = 100
            title_color = (255, 255, 255, 255) # Branco

            # --- Configurações Individuais dos Jogadores ---
            
            # Posição X das colunas (centralizado, esquerda e direita)
            center_x = background.width // 2
            col_left_x = background.width // 4
            col_right_x = background.width - (background.width // 4)
            
            # Lista de configurações para cada um dos 5 jogadores
            # Mude os valores aqui para ajustar cada jogador individualmente.
            player_configs = [
                # Jogador 1 (Centralizado no topo)
                {
                    'x': center_x,
                    'y': 350,
                    'name_font_size': 70,
                    'stats_font_size': 40,
                    'name_stats_spacing': 70
                },
                # Jogador 2 (Esquerda)
                {
                    'x': col_left_x,
                    'y': 520,
                    'name_font_size': 60,
                    'stats_font_size': 35,
                    'name_stats_spacing': 60
                },
                # Jogador 3 (Direita)
                {
                    'x': col_right_x,
                    'y': 520,
                    'name_font_size': 60,
                    'stats_font_size': 35,
                    'name_stats_spacing': 60
                },
                # Jogador 4 (Esquerda, abaixo do Jogador 2)
                {
                    'x': col_left_x,
                    'y': 650,
                    'name_font_size': 60,
                    'stats_font_size': 35,
                    'name_stats_spacing': 60
                },
                # Jogador 5 (Direita, abaixo do Jogador 3)
                {
                    'x': col_right_x,
                    'y': 650,
                    'name_font_size': 60,
                    'stats_font_size': 35,
                    'name_stats_spacing': 60
                }
            ]

            # Cores do texto
            name_color = (255, 255, 0, 255) # Amarelo para nomes
            stats_color = (173, 216, 230, 255) # Azul claro para stats

            # --- Configurações do Rodapé ---
            footer_text = f"Última atualização: {last_updated}"
            footer_x, footer_y = background.width // 2, background.height - 50
            footer_font_size = 25
            footer_color = (255, 255, 255, 255) # Branco

            # =================================================================
            # === FIM DAS CONFIGURAÇÕES ===
            # =================================================================

            # Desenha o Título
            self._draw_text_with_options(draw, title_text, title_x, title_y, title_font_size, title_color, centered=True)

            # Desenha os Jogadores, iterando sobre a lista de configurações
            for i, player in enumerate(top_players):
                # Pega a configuração específica para este jogador
                config = player_configs[i]
                
                player_name = f"{player['name']}"
                rank_points_text = f"Rank: {player['rank']} | Pontos: {player['rankPoints']}"

                # Desenha o nome usando as configurações
                self._draw_text_with_options(
                    draw, 
                    player_name, 
                    config['x'], 
                    config['y'], 
                    config['name_font_size'], 
                    name_color, 
                    centered=True
                )
                
                # Desenha o rank/pontos
                self._draw_text_with_options(
                    draw, 
                    rank_points_text, 
                    config['x'], 
                    config['y'] + config['name_stats_spacing'], 
                    config['stats_font_size'], 
                    stats_color, 
                    centered=True
                )

            # Desenha o Rodapé
            self._draw_text_with_options(draw, footer_text, footer_x, footer_y, footer_font_size, footer_color, centered=True)

            img_byte_arr = io.BytesIO()
            background.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            return img_byte_arr

        except FileNotFoundError:
            logger.error(f"Erro: Arquivo de imagem de fundo '{self.background_image_path}' ou fonte '{self.font_path}' não encontrado.")
            return None
        except Exception as e:
            logger.error(f"Erro ao gerar imagem do leaderboard: {e}", exc_info=True)
            return None

    @app_commands.command(name="leaderboard", description="Mostra os 5 melhores jogadores de um Tier específico do leaderboard ranqueado do PUBG.")
    @is_rank_channel_check
    @app_commands.choices(tier_selection=[
        app_commands.Choice(name="Survivor", value="Survivor"),
        app_commands.Choice(name="Master", value="Master"),
        app_commands.Choice(name="Diamond", value="Diamond"),
        app_commands.Choice(name="Crystal", value="Crystal"),         
        app_commands.Choice(name="Platinum", value="Platinum"),
    ])
    async def leaderboard(self, interaction: discord.Interaction, tier_selection: app_commands.Choice[str]):
        await interaction.response.defer()

        selected_tier = tier_selection.value

        if not os.path.exists(self.json_file_path):
            embed = discord.Embed(
                title="❌ Leaderboard Não Encontrado",
                description="O arquivo do leaderboard não foi encontrado. Por favor, aguarde a primeira atualização ou tente novamente mais tarde.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return

        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            squad_fpp_data = data.get('squad-fpp')
            if not squad_fpp_data or 'included' not in squad_fpp_data:
                embed = discord.Embed(
                    title="❌ Dados do Leaderboard Inválidos",
                    description="O arquivo do leaderboard está vazio ou com formato inesperado para 'squad-fpp'.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return

            players_data_raw = squad_fpp_data['included']
            
            valid_players = []
            for item in players_data_raw:
                if item.get('type') == 'player' and 'attributes' in item:
                    attributes = item['attributes']
                    stats = attributes.get('stats')

                    player_name = attributes.get('name') 
                    player_rank = attributes.get('rank')
                    player_rank_points = stats.get('rankPoints') if stats else None 

                    player_tier = stats.get('tier') if stats else None
                    player_sub_tier = stats.get('subTier') if stats else None
                    
                    if player_name and player_rank is not None and \
                       player_tier and player_sub_tier is not None and \
                       player_rank_points is not None:
                        
                        valid_players.append({
                            'name': player_name,
                            'tier': player_tier,
                            'subTier': player_sub_tier,
                            'rank': player_rank,
                            'rankPoints': player_rank_points
                        })
            
            if not valid_players:
                embed = discord.Embed(
                    title="⚠️ Nenhum Jogador Válido",
                    description="Não foram encontrados jogadores válidos com dados de tier/rank no leaderboard. Verifique se o JSON contém os campos 'name', 'rank' (em 'attributes') e 'tier', 'subTier', 'rankPoints' (em 'attributes.stats') dos jogadores em 'included'.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return

            selected_tier_players = [
                player for player in valid_players if player['tier'] == selected_tier
            ]

            if not selected_tier_players:
                embed = discord.Embed(
                    title=f"⚠️ Nenhum Jogador Encontrado para o Tier {selected_tier}",
                    description="Não foram encontrados jogadores para este tier no leaderboard atualmente.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return

            tier_players_sorted = sorted(selected_tier_players, key=lambda p: p['rank'])
            
            top_5_players = tier_players_sorted[:5]

            last_modified_time = "N/A"
            if os.path.exists(self.json_file_path):
                timestamp = os.path.getmtime(self.json_file_path)
                dt_object = datetime.datetime.fromtimestamp(timestamp, tz=pytz.timezone('America/Sao_Paulo'))
                last_modified_time = dt_object.strftime('%d/%m/%Y %H:%M:%S')

            leaderboard_image_buffer = await self.generate_leaderboard_image(selected_tier, top_5_players, last_modified_time)

            if leaderboard_image_buffer:
                file = discord.File(leaderboard_image_buffer, filename=f"leaderboard_{selected_tier}.png")
                await interaction.followup.send(file=file)
            else:
                embed = discord.Embed(
                    title="❌ Erro ao Gerar Imagem",
                    description="Ocorreu um erro ao gerar a imagem do leaderboard. Contate o desenvolvedor.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)


        except FileNotFoundError:
            embed = discord.Embed(
                title="❌ Erro de Arquivo",
                description="O arquivo JSON do leaderboard não foi encontrado. Por favor, aguarde a atualização automática.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
        except json.JSONDecodeError:
            embed = discord.Embed(
                title="❌ Erro no JSON",
                description="O arquivo do leaderboard está corrompido ou com formato inválido.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Erro ao processar e enviar leaderboard: {e}", exc_info=True)
            embed = discord.Embed(
                title="❌ Erro Inesperado",
                description=f"Ocorreu um erro inesperado ao gerar o leaderboard: `{type(e).__name__}`. Contate o desenvolvedor.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))