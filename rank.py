import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
import asyncio
import logging

# Importa o check personalizado
from defi.checks import is_rank_channel_check

logger = logging.getLogger(__name__)

# Dicionário de imagens dos ranks (Mantido)
RANK_IMAGES = {
    "Unranked": "https://i.postimg.cc/75NSKRQT/unranked-removebg-preview.png",
    "Bronze 1": "https://i.postimg.cc/34tLzRSm/bronze1-removebg-preview.png",
    "Bronze 2": "https://i.postimg.cc/xqFxRXbS/bronze2-removebg-preview.png",
    "Bronze 3": "https://i.postimg.cc/Btv7HTbg/bronze3-removebg-preview.png",
    "Bronze 4": "https://i.postimg.cc/ct6DWS2j/bronze4-removebg-preview.png",
    "Bronze 5": "https://i.postimg.cc/BXLhwJxP/bronze5-removebg-preview.png",
    "Silver 1": "https://i.postimg.cc/JHBbK491/prata1-removebg-preview.png",
    "Silver 2": "https://i.postimg.cc/t71t927L/prata2-removebg-preview.png",
    "Silver 3": "https://i.postimg.cc/grfyj8Zr/prata3-removebg-preview.png",
    "Silver 4": "https://i.postimg.cc/7f032h39/prata4-removebg-preview.png",
    "Silver 5": "https://i.postimg.cc/ZWmrFmjS/prata5-removebg-preview.png",
    "Gold 1": "https://i.postimg.cc/jw3XZ12h/ouro1-removebg-preview.png",
    "Gold 2": "https://i.postimg.cc/V0SFTFbP/ouro2-removebg-preview.png",
    "Gold 3": "https://i.postimg.cc/mhqj9K0L/ouro3-removebg-preview.png",
    "Gold 4": "https://i.postimg.cc/MvQDmdSy/ouro4-removebg-preview-2.png",
    "Gold 5": "https://i.postimg.cc/zyYktKz4/ouro5-removebg-preview.png",
    "Platinum 1": "https://i.postimg.cc/G4PxZt9t/platina1-removebg-preview.png",
    "Platinum 2": "https://i.postimg.cc/t1XNybV5/platina2-removebg-preview.png",
    "Platinum 3": "https://i.postimg.cc/CZmHx2GV/platina3-removebg-preview.png",
    "Platinum 4": "https://i.postimg.cc/ZBnPBLHv/platina4-removebg-preview.png",
    "Platinum 5": "https://i.postimg.cc/62PrdGbj/platina5-removebg-preview.png",
    "Crystal 1": "https://i.postimg.cc/bJs8tpzf/Chat-GPT-Image-8-de-jun-de-2025-09-08-52.png",
    "Crystal 2": "https://i.postimg.cc/bJs8tpzf/Chat-GPT-Image-8-de-jun-de-2025-09-08-52.png",
    "Crystal 3": "https://i.postimg.cc/bJs8tpzf/Chat-GPT-Image-8-de-jun-de-2025-09-08-52.png",
    "Crystal 4": "https://i.postimg.cc/bJs8tpzf/Chat-GPT-Image-8-de-jun-de-2025-09-08-52.png",
    "Crystal 5": "https://i.postimg.cc/bJs8tpzf/Chat-GPT-Image-8-de-jun-de-2025-09-08-52.png",
    "Diamond 1": "https://i.postimg.cc/dLb5bgBH/dima1-removebg-preview.png",
    "Diamond 2": "https://i.postimg.cc/5X8sbpKx/dima2-removebg-preview.png",
    "Diamond 3": "https://i.postimg.cc/rdcQmW75/dima3-removebg-preview.png",
    "Diamond 4": "https://i.postimg.cc/JyqKB0Wv/dima4-removebg-preview.png",
    "Diamond 5": "https://i.postimg.cc/ZB5HPmbR/dima5-removebg-preview.png",
    "Master 1": "https://i.postimg.cc/NLLb5QCC/mestre-removebg-preview.png",
    "Survivor 1": "https://i.postimg.cc/s2nsxvCJ/survivor-medal-transparent.png",
}

GAME_MODES = {
    "Ranked Squad-FPP": ("ranked", "squad-fpp"),
    "Normal Solo-FPP": ("normal", "solo-fpp"),
    "Normal Duo-FPP": ("normal", "duo-fpp"),
    "Normal Squad-FPP": ("normal", "squad-fpp")
}

PUBG_API_BASE_URL = "https://api.pubg.com/shards/steam"

current_season_id_cache = None
player_id_cache = {}

rank_info_role_names = {
    "Bronze I 🥉", "Bronze II 🥉", "Bronze III 🥉", "Bronze IV 🥉",
    "Silver I 🥈", "Silver II 🥈", "Silver III 🥈", "Silver IV 🥈",
    "Gold I 🥇", "Gold II 🥇", "Gold III 🥇", "Gold IV 🥇",
    "Platinum I 💠", "Platinum II 💠", "Platinum III 💠", "Platinum IV 💠",
    "Crystal I 🔮", "Crystal II 🔮", "Crystal III 🔮", "Crystal IV 🔮",
    "Diamond I 💎", "Diamond II 💎", "Diamond III 💎", "Diamond IV 💎",
    "Master 🏆",
    "Survivor 💪",
}


API_RANK_TO_ROLENAME = {
    "Bronze 1": "Bronze I 🥉", "Bronze 2": "Bronze II 🥉", "Bronze 3": "Bronze III 🥉", "Bronze 4": "Bronze IV 🥉",
    "Bronze 5": "Bronze V 🥉",
    "Silver 1": "Silver I 🥈", "Silver 2": "Silver II 🥈", "Silver 3": "Silver III 🥈", "Silver 4": "Silver IV 🥈",
    "Silver 5": "Silver V 🥈",
    "Gold 1": "Gold I 🥇", "Gold 2": "Gold II 🥇", "Gold 3": "Gold III 🥇", "Gold 4": "Gold IV 🥇",
    "Gold 5": "Gold V 🥇",
    "Platinum 1": "Platinum I 💠", "Platinum 2": "Platinum II 💠", "Platinum 3": "Platinum III 💠", "Platinum 4": "Platinum IV 💠",
    "Platinum 5": "Platinum V 💠",
    "Crystal 1": "Crystal I 🔮", "Crystal 2": "Crystal II 🔮", "Crystal 3": "Crystal III 🔮", "Crystal 4": "Crystal IV 🔮",
    "Crystal 5": "Crystal V 🔮", # Adicionado Crystal 5, se aplicável
    "Diamond 1": "Diamond I 💎", "Diamond 2": "Diamond II 💎", "Diamond 3": "Diamond III 💎", "Diamond 4": "Diamond IV 💎",
    "Diamond 5": "Diamond V 💎",
    "Master 1": "Master 🏆",
    "Survivor 1": "Survivor 💪",
    "Unranked": None
}

class PUBGAPIError(Exception):
    """Exceção personalizada para erros da API do PUBG que precisam ser propagados."""
    def __init__(self, status_code: int, message: str, url: str, *args):
        super().__init__(*args)
        self.status_code = status_code
        self.message = message
        self.url = url

async def get_current_season_id(session: aiohttp.ClientSession, headers: dict) -> str | None:
    global current_season_id_cache
    if current_season_id_cache:
        logger.debug("Retornando ID da temporada do cache global.")
        return current_season_id_cache

    seasons_url = f"{PUBG_API_BASE_URL}/seasons"
    logger.debug(f"Buscando ID da temporada da API: {seasons_url}")
    try:
        async with session.get(seasons_url, headers=headers, timeout=10) as response:
            response.raise_for_status()
            seasons_data = await response.json()

        current_season = next((s for s in seasons_data.get("data", []) if s.get("attributes", {}).get("isCurrentSeason")), None)
        if current_season:
            current_season_id_cache = current_season.get("id")
            logger.info(f"ID da temporada atual encontrado e salvo no cache global: {current_season_id_cache}")
            return current_season_id_cache
        logger.warning("Temporada atual não encontrada na resposta da API de seasons.")
        return None

    except aiohttp.ClientResponseError as e:
        logger.error(f"Erro na requisição HTTP para a API do PUBG (get_current_season_id): Status {e.status} - {e.message}", exc_info=True)
        raise e
    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
        logger.error(f"Erro de conexão/timeout com a API do PUBG (get_current_season_id): {type(e).__name__} - {e}", exc_info=True)
        raise e
    except Exception as e:
        logger.error(f"Erro inesperado em get_current_season_id: {type(e).__name__} - {e}", exc_info=True)
        raise e


async def get_player_id(session: aiohttp.ClientSession, headers: dict, player_name: str) -> str | None:
    global player_id_cache
    if player_name in player_id_cache:
        logger.debug(f"Retornando Account ID para '{player_name}' do cache global.")
        return player_id_cache[player_name]

    player_url = f"{PUBG_API_BASE_URL}/players?filter[playerNames]={player_name}"
    logger.debug(f"Buscando Account ID para '{player_name}' da API: {player_url}")
    try:
        async with session.get(player_url, headers=headers, timeout=10) as response:
            if response.status == 404:
                logger.debug(f"Jogador '{player_name}' não encontrado na API (404).")
                return None
            
            response.raise_for_status()

            player_data = await response.json()

        if not player_data or not player_data.get("data"):
            logger.debug(f"Jogador '{player_name}' não encontrado na API (payload vazio).")
            return None

        account_id = player_data["data"][0]["id"]
        player_id_cache[player_name] = account_id
        logger.info(f"Account ID encontrado para '{player_name}' e salvo no cache global: {account_id}")
        return account_id

    except aiohttp.ClientResponseError as e:
        logger.error(f"Erro na requisição HTTP para a API do PUBG (get_player_id): Status {e.status} - {e.message}", exc_info=True)
        raise e
    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
        logger.error(f"Erro de conexão/timeout com a API do PUBG (get_player_id) para '{player_name}': {type(e).__name__} - {e}", exc_info=True)
        raise e
    except Exception as e:
        logger.error(f"Erro inesperado em get_player_id para '{player_name}': {type(e).__name__} - {e}", exc_info=True)
        raise e


class PUBGStats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # REMOÇÃO: A lógica de inicialização/reabertura da aiohttp.ClientSession foi removida.
        # Agora, a cog apenas verifica se a sessão já existe no objeto 'bot', conforme a abordagem de gerenciamento centralizado.
        if not hasattr(bot, 'http_session') or bot.http_session is None:
            logger.critical("aiohttp.ClientSession não foi inicializada no bot! PUBGStats Cog não pode ser carregada corretamente.")
            # É crucial que a sessão exista para que esta cog funcione, então levantamos um erro.
            raise RuntimeError("aiohttp.ClientSession não inicializada. Verifique a ordem de carregamento ou o main.py.")
        
        self.pubg_api_key = os.getenv('PUBG_API_KEY')
        if not self.pubg_api_key:
            logger.error("PUBG API Key não encontrada nas variáveis de ambiente. O comando '/rank' pode não funcionar.")


    @app_commands.command(name='rank', description='Consulta as estatísticas da temporada do jogador PUBG.')
    @is_rank_channel_check
    @app_commands.describe(
        player_name="Nome do jogador PUBG para consultar (obrigatório)",
        mode="Modo de jogo para consulta (obrigatório)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Ranked Squad-FPP", value="Ranked Squad-FPP"),
        app_commands.Choice(name="Normal Solo-FPP", value="Normal Solo-FPP"),
        app_commands.Choice(name="Normal Duo-FPP", value="Normal Duo-FPP"),
        app_commands.Choice(name="Normal Squad-FPP", value="Normal Squad-FPP"),
    ])
    async def rank(self, interaction: discord.Interaction, player_name: str, mode: app_commands.Choice[str]):
        logger.info(f"Comando rank executado por {interaction.user.id} ({interaction.user}) em guild {interaction.guild_id}. player_name={player_name}, mode={mode.value}")

        if not self.pubg_api_key:
            logger.error("PUBG API Key não configurada ao executar comando rank.")
            await interaction.response.send_message(
                "❌ Erro interno: A chave da API do PUBG não está configurada no bot. Por favor, avise um administrador.",
                ephemeral=True
            )
            return

        pubg_nickname = player_name
        logger.debug(f"Usando nickname PUBG fornecido: {pubg_nickname}")

        headers = {
            "Authorization": f"Bearer {self.pubg_api_key}",
            "Accept": "application/vnd.api+json"
        }

        # A sessão agora é acessada diretamente do bot.
        # Não há mais a verificação `session.closed` aqui, pois a sessão global do bot deve ser sempre tratada como aberta
        # ou reaberta pelo processo principal do bot (no main.py).
        session = self.bot.http_session

        # Uma verificação básica para garantir que a sessão não seja None, embora o __init__ já deva ter garantido isso.
        if session is None:
            logger.critical("aiohttp session é None ao executar comando rank. Isso não deveria acontecer após a inicialização da cog.")
            await interaction.response.send_message("❌ Erro interno: Sessão HTTP indisponível. Por favor, avise um administrador do bot.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        
        try:
            # --- Etapa 1: Buscar ID do jogador ---
            account_id = await get_player_id(session, headers, pubg_nickname)
            if account_id is None:
                await interaction.followup.send(
                    f"O Nickname **{pubg_nickname}** não foi encontrado. Verifique se digitou corretamente.",
                    ephemeral=True 
                )
                return

            # --- Etapa 2: Buscar ID da temporada atual ---
            season_id = await get_current_season_id(session, headers)
            if not season_id:
                await interaction.followup.send("❌ Temporada atual não encontrada na API do PUBG. Tente novamente mais tarde.", ephemeral=True) 
                return

            mode_label = mode.value
            if mode_label not in GAME_MODES:
                logger.error(f"Modo de jogo '{mode_label}' inválido recebido do Discord.")
                await interaction.followup.send("❌ Modo de jogo inválido selecionado.", ephemeral=True) 
                return

            mode_type, game_mode = GAME_MODES[mode_label]

            # --- Etapa 3: Construir URL e buscar estatísticas ---
            if mode_type == "ranked":
                stats_url = f"{PUBG_API_BASE_URL}/players/{account_id}/seasons/{season_id}/ranked"
            else:
                stats_url = f"{PUBG_API_BASE_URL}/players/{account_id}/seasons/{season_id}"

            logger.debug(f"Buscando stats para jogador {account_id} no modo {mode_label}: {stats_url}")

            async with session.get(stats_url, headers=headers, timeout=10) as response:
                if response.status == 404:
                    logger.info(f"Estatísticas não encontradas (404) para jogador {pubg_nickname}, modo {mode_label}, temporada {season_id}")
                    await interaction.followup.send(f"❌ Estatísticas não encontradas para o modo **{mode_label}** nesta temporada (o jogador pode não ter jogado este modo).", ephemeral=True)
                    return
                response.raise_for_status()
                data = await response.json()

            # Lógica para extrair as estatísticas
            stats = None
            if mode_type == "ranked":
                stats = data.get("data", {}).get("attributes", {}).get("rankedGameModeStats", {}).get(game_mode)
                if not stats: # Fallback para "All" se o modo específico não for encontrado para rankeado
                    stats = data.get("data", {}).get("attributes", {}).get("rankedGameModeStats", {}).get("All")
            else:
                stats = data.get("data", {}).get("attributes", {}).get("gameModeStats", {}).get(game_mode)
                if not stats: # Fallback para "All" se o modo específico não for encontrado para normal
                    stats = data.get("data", {}).get("attributes", {}).get("gameModeStats", {}).get("All")

            if not stats:
                logger.info(f"Estatísticas não encontradas (payload vazio) para jogador {pubg_nickname}, modo {mode_label}, temporada {season_id}")
                await interaction.followup.send(f"❌ Estatísticas não encontradas para o modo **{mode_label}** nesta temporada (o jogador pode não ter jogado este modo).", ephemeral=True) 
                return

            # --- Processar Dados do Rank e Pontos ---
            rank_str = "Unranked"
            current_points = "Não aplicável"
            best_points = "Não aplicável"

            if mode_type == "ranked":
                tier_info = stats.get("currentTier", {"tier": "Unranked", "subTier": ""})
                tier = tier_info.get("tier", "Unranked")
                sub_tier = tier_info.get("subTier", "")
                rank_str = f"{tier} {sub_tier}".strip() if sub_tier else tier

                raw_current_points = stats.get("currentRankPoint", 0)
                raw_best_points = stats.get("bestRankPoint", 0)
                current_points = raw_current_points if isinstance(raw_current_points, (int, float)) else "Não aplicável"
                best_points = raw_best_points if isinstance(raw_best_points, (int, float)) else "Não aplicável"

            logger.info(f"Stats obtidos para {pubg_nickname}, Rank API: {rank_str}")

            # --- Início da Lógica de Atribuição de Cargos ---
            if interaction.guild and mode_type == "ranked":
                member = interaction.user
                db_manager = self.bot.db_manager

                if db_manager is None:
                    logger.error(f"DatabaseCog não está disponível no bot para guilda {interaction.guild_id}. Não é possível verificar/atualizar cargo.")
                    await interaction.followup.send("❌ Erro interno: O gerenciador de banco de dados não está disponível para verificar o link da sua conta.", ephemeral=True) 
                    return

                try:
                    is_linked_account_lookup = await db_manager.is_pubg_nickname_linked_to_user(member.id, pubg_nickname)

                    if is_linked_account_lookup:
                        logger.debug(f"Nickname fornecido '{pubg_nickname}' corresponde ao link para user {member.id}. Tentando atualizar cargo.")

                        if interaction.guild.me.guild_permissions.manage_roles:
                            try:
                                current_roles = member.roles

                                existing_rank_roles = [
                                    role for role in current_roles
                                    if role.name in rank_info_role_names
                                ]
                                logger.debug(f"User {member.id} possui os seguintes cargos de rank gerenciados: {[r.name for r in existing_rank_roles]}")

                                target_role_name = API_RANK_TO_ROLENAME.get(rank_str)
                                logger.debug(f"Nome do cargo alvo no Discord para rank API '{rank_str}': '{target_role_name}'")

                                roles_to_remove = existing_rank_roles.copy()
                                roles_to_add = []

                                if target_role_name:
                                    target_role = discord.utils.get(interaction.guild.roles, name=target_role_name)
                                    if target_role:
                                        if target_role in roles_to_remove:
                                            roles_to_remove.remove(target_role)
                                        elif target_role not in current_roles:
                                            roles_to_add.append(target_role)
                                    else:
                                        logger.warning(f"Cargo alvo '{target_role_name}' (obtido do rank API '{rank_str}') não encontrado no guild {interaction.guild.id}. Pulando adição.")

                                if roles_to_remove:
                                    logger.info(f"Removendo cargos: {[r.name for r in roles_to_remove]} de user {member.id} em guild {interaction.guild.id}")
                                    await member.remove_roles(*roles_to_remove, reason=f"Atualizando rank PUBG para {rank_str}")

                                if roles_to_add:
                                    logger.info(f"Adicionando cargo: {roles_to_add[0].name} para user {member.id} em guild {interaction.guild.id}")
                                    await member.add_roles(*roles_to_add, reason=f"Atualizando rank PUBG para {rank_str}")

                            except discord.Forbidden:
                                logger.warning(f"Bot sem permissão (Forbidden) para gerenciar cargos de rank para user {member.id} em guild {interaction.guild.id}. Sem atualizar cargo.", exc_info=True)
                                await interaction.followup.send("⚠️ Não tenho permissão para atualizar seu cargo de rank (verifique a hierarquia de cargos).", ephemeral=False) 
                                return
                            except discord.HTTPException as e:
                                logger.error(f"HTTP error durante atualização de cargo para user {member.id} em guild {interaction.guild.id}: {e}", exc_info=True)
                                await interaction.followup.send("❌ Ocorreu um erro ao tentar atualizar seu cargo de rank.", ephemeral=False) 
                                return
                            except Exception as e:
                                logger.error(f"Erro inesperado durante atualização de cargo para user {member.id} em guild {interaction.guild.id}: {e}", exc_info=True)
                                await interaction.followup.send("❌ Ocorreu um erro inesperado ao tentar atualizar seu cargo de rank.", ephemeral=False) 
                                return

                        else: 
                            logger.warning(f"Bot sem a permissão 'manage_roles' geral em guild {interaction.guild.id}. Sem atualizar cargo.")
                            await interaction.followup.send("⚠️ Não tenho permissão para gerenciar cargos neste servidor, não posso atualizar seu rank.", ephemeral=False) 
                            return

                    else:
                        logger.debug(f"Nickname fornecido '{pubg_nickname}' NÃO corresponde ao link para user {member.id}. Pulando atualização de cargo.")

                except Exception as e:
                    logger.error(f"Erro inesperado ao verificar/atualizar cargo de rank para user {member.id}: {e}", exc_info=True)
                    await interaction.followup.send("❌ Ocorreu um erro inesperado ao tentar verificar/atualizar seu cargo de rank.", ephemeral=True) 
                    return
            elif interaction.guild and mode_type != "ranked":
                logger.debug("Comando em modo normal. Pulando atualização de cargo.")
            elif not interaction.guild:
                logger.debug("Comando executado em DM. Pulando atualização de cargo.")

            # --- Fim da Lógica de Atribuição de Cargos ---

            # --- Construção e Envio do Embed ---
            embed = discord.Embed(title=f"Estatísticas de {pubg_nickname}", color=discord.Color.blue())
            season_number = season_id.split("-")[-1] if season_id else "N/A"

            embed.add_field(name="Modo 🛠️", value=mode_label, inline=False)
            embed.add_field(name="Temporada 🏆", value=f"`{season_number}`", inline=True)

            embed.add_field(name="Rank 🏅", value=f"**{rank_str}**", inline=True) 
            if mode_type == "ranked":
                current_points_display = f"`{int(current_points):,}`" if isinstance(current_points, (int, float)) else f"`{current_points}`"
                best_points_display = f"`{int(best_points):,}`" if isinstance(best_points, (int, float)) else f"`{best_points}`"
                embed.add_field(name="Pontos Atuais 🎖️", value=current_points_display, inline=True)
                embed.add_field(name="Melhor Pontuação 💎", value=best_points_display, inline=True)
            else: 
                embed.add_field(name="Pontos Atuais 🎖️", value=f"`{current_points}`", inline=True)
                embed.add_field(name="Melhor Pontuação 💎", value=f"`{best_points}`", inline=True)


            embed.add_field(name="Kills ⚔️", value=f"`{stats.get('kills', 0)}`", inline=True)
            embed.add_field(name="Deaths 💀", value=f"`{stats.get('deaths', 0)}`", inline=True)
            embed.add_field(name="Assists 🤝", value=f"`{stats.get('assists', 0)}`", inline=True)
            kda = stats.get('kda', 0)
            if isinstance(kda, (int, float)):
                embed.add_field(name="K/D 🔪", value=f"`{float(kda):.1f}`", inline=True)
            else:
                embed.add_field(name="K/D 🔪", value=f"`{kda}`", inline=True)


            embed.add_field(name="Vitórias 🏆", value=f"`{stats.get('wins', 0)}`", inline=True)
            win_ratio = stats.get('winRatio', 0)
            if isinstance(win_ratio, (int, float)):
                embed.add_field(name="Taxa de Vitória 💯", value=f"`{float(win_ratio)*100:.2f}%`", inline=True)
            else:
                embed.add_field(name="Taxa de Vitória 💯", value=f"`{win_ratio}`", inline=True)


            damage_dealt = stats.get('damageDealt', 0)
            if isinstance(damage_dealt, (int, float)):
                embed.add_field(name="Dano Total 💥 ", value=f"`{int(float(damage_dealt)):,}`", inline=True)
            else:
                embed.add_field(name="Dano Total 💥 ", value=f"`{damage_dealt}`", inline=True)


            embed.add_field(name="Derrubadas 💤", value=f"`{stats.get('dBNOs', 0)}`", inline=True)

            rounds_played = stats.get('roundsPlayed', 0)
            top10_ratio = stats.get('top10Ratio', 0)

            if isinstance(rounds_played, (int, float)) and isinstance(top10_ratio, (int, float)):
                num_top10s = round(rounds_played * top10_ratio)
                embed.add_field(name="Top 10 📊", value=f"`{num_top10s}`", inline=True)
            else:
                embed.add_field(name="Top 10 📊", value="`N/A`", inline=True)


            if isinstance(top10_ratio, (int, float)):
                embed.add_field(name="Top 10 Ratio 🔝", value=f"`{float(top10_ratio)*100:.2f}%`", inline=True)
            else:
                embed.add_field(name="Top 10 Ratio 🔝", value=f"`{top10_ratio}`", inline=True)


            avg_rank_pos = stats.get('avgRank', 0)
            if isinstance(avg_rank_pos, (int, float)):
                embed.add_field(name="Rank Médio Posição 🥉", value=f"`{float(avg_rank_pos):.2f}`", inline=True)
            else:
                embed.add_field(name="Rank Médio Posição 🥉", value=f"`{avg_rank_pos}`", inline=True)


            embed.set_footer(text="Estatísticas atualizadas.")
            embed.set_thumbnail(url=RANK_IMAGES.get(rank_str, RANK_IMAGES.get("Unranked", None))) 

            await interaction.followup.send(embed=embed, ephemeral=False) # Usar followup.send após defer
            
            logger.info(f"Embed de rank enviado para {pubg_nickname} ({mode_label})")

        except aiohttp.ClientResponseError as e:
            logger.error(f"Erro na requisição HTTP para a API do PUBG: Status {e.status} - {e.message}", exc_info=True)
            if e.status == 401 or e.status == 403:
                await interaction.followup.send("❌ Erro de autenticação com a API do PUBG. Verifique a chave da API e se ela tem permissões.", ephemeral=True)
            elif e.status == 429:
                await interaction.followup.send("⏳ Rate limit da API do PUBG atingido. Tente novamente em breve.", ephemeral=True)
            elif e.status == 504: 
                await interaction.followup.send("⏳ A API do PUBG demorou muito para responder (Gateway Timeout). Por favor, tente novamente em breve. Isso geralmente indica um problema temporário no servidor do jogo.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Erro na requisição HTTP para a API do PUBG: Status {e.status}", ephemeral=True)
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
            logger.error(f"Erro de conexão/timeout com a API do PUBG: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Erro de conexão com a API do PUBG ou timeout. Verifique a conexão do bot ou tente novamente mais tarde.", ephemeral=True)
        except KeyError as e:
            logger.error(f"Erro ao processar dados da API (KeyError): Chave faltando - {e}", exc_info=True)
            await interaction.followup.send(f"❌ Ocorreu um erro ao processar os dados do rank. Os dados da API podem ter mudado inesperadamente.", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro inesperado no comando rank para user {interaction.user.id}: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Ocorreu um erro inesperado ao consultar o rank: {type(e).__name__}", ephemeral=True)


# --- Função setup para Adicionar o Cog ao Bot ---
async def setup(bot: commands.Bot):
    # Não há mais a verificação bot.http_session aqui, pois o __init__ da cog já a faz,
    # e a expectativa é que o main.py garanta a sessão antes de carregar as cogs.
    await bot.add_cog(PUBGStats(bot))
    logger.info("Cog 'PUBGStats' carregada com sucesso.")