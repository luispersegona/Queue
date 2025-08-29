import discord
from discord.ext import commands
from discord import app_commands
import json, os, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import asyncio
import functools
import aiohttp

# Importa o check personalizado (mantenha seu caminho correto)
from defi.checks import is_rank_channel_check

# ================================================================
# CONTEÚDO COMPLETO DE SEU telemetry.py
# ================================================================
class TeleProcessor:
    def __init__(self, telemetryFile):
        """
        Inicializa o TeleProcessor carregando os dados de telemetria de um arquivo JSON.
        """
        try:
            with open(telemetryFile, 'r', encoding='utf-8') as f:
                self.telemetry = json.load(f)
        except FileNotFoundError:
            print(f"Erro: Arquivo de telemetria não encontrado em {telemetryFile}")
            self.telemetry = []
        except json.JSONDecodeError:
            print(f"Erro: Arquivo {telemetryFile} não é um JSON válido.")
            self.telemetry = []
        except Exception as e:
            print(f"Erro ao carregar telemetria de {telemetryFile}: {e}")
            self.telemetry = []

    def get_player_team_id(self, player_name: str) -> int | None:
        """
        Busca o teamId de um jogador específico nos eventos LogPlayerCreate.
        """
        for event in self.telemetry:
            if event.get('_T') == 'LogPlayerCreate' and \
               'character' in event and \
               event['character'].get('name') == player_name:
                return event['character'].get('teamId')
        return None

    def get_team_members(self, team_id: int) -> list[str]:
        """
        Retorna uma lista de nicknames de todos os jogadores com um dado teamId,
        baseado nos eventos LogPlayerCreate.
        """
        team_members = set()
        for event in self.telemetry:
            if event.get('_T') == 'LogPlayerCreate' and \
               'character' in event and \
               event['character'].get('teamId') == team_id:
                member_name = event['character'].get('name')
                if member_name:
                    team_members.add(member_name)
        return list(team_members)

    def getPlayerXY(self, player=None):
        """
        Obtém as coordenadas X e Y de todos os eventos LogPlayerPosition,
        opcionalmente filtrando por um jogador específico.
        Retorna uma lista de dicionários com 'x', 'y' e 'time'.

        AJUSTE CRÍTICO: Reestrutura a lógica para garantir o kill_break e o trajeto pós-morte,
        agora lidando com 'elapsedTime' e '_D' para o tempo do evento.
        """
        loc_data = []
        kill_events = []

        # Encontra o tempo de início da partida para normalizar os timestamps _D
        match_start_time = None
        for event in self.telemetry:
            if event.get('_T') == 'LogMatchStart':
                # Preferimos 'elapsedTime' se existir, caso contrário usamos '_D'
                match_start_time = event.get('elapsedTime')
                if match_start_time is None: # Se não tem elapsedTime, usa _D
                    try:
                        match_start_time = datetime.strptime(event['_D'], '%Y-%m-%dT%H:%M:%S.%fZ').timestamp()
                    except (ValueError, KeyError):
                        pass # Continua procurando ou usa 0 como fallback se não encontrar
                break

        # Se não encontrarmos um LogMatchStart com elapsedTime ou _D, assumimos 0
        # Isso pode causar imprecisões se as primeiras posições não estiverem perto de 0
        if match_start_time is None:
            match_start_time = 0
            print("AVISO: Tempo de início da partida (LogMatchStart) não encontrado ou inválido. Assumindo tempo 0 para cálculos de telemetria.")


        # Coleta e filtra eventos de posição e morte para o jogador
        for event in self.telemetry:
            event_type = event.get('_T')

            # Tenta obter elapsedTime. Se não, tenta converter _D para segundos desde o início
            event_time = event.get('elapsedTime')
            if event_time is None and '_D' in event:
                try:
                    current_event_timestamp_utc = datetime.strptime(event['_D'], '%Y-%m-%dT%H:%M:%S.%fZ').timestamp()
                    # Calcula o tempo decorrido em segundos desde o início da partida
                    event_time = current_event_timestamp_utc - match_start_time
                    if event_time < 0: # Caso o evento tenha ocorrido antes do MatchStart (ajuste)
                        event_time = 0
                except (ValueError, KeyError):
                    event_time = 0 # Fallback se _D for inválido ou ausente

            # Ignora eventos com tempo <= 0 ou sem tempo válido
            if event_time is None or event_time <= 0:
                continue

            if event_type == 'LogPlayerPosition':
                if player:
                    if 'character' in event and 'name' in event['character'] and event['character']['name'] == player:
                        if 'location' in event['character']:
                            loc_data.append({
                                'x': event['character']['location']['x'],
                                'y': event['character']['location']['y'],
                                'time': event_time, # Usando o tempo normalizado
                                'type': 'position'
                            })
                else:
                    if 'character' in event and 'location' in event['character']:
                            loc_data.append({
                                'x': event['character']['location']['x'],
                                'y': event['character']['location']['y'],
                                'time': event_time, # Usando o tempo normalizado
                                'type': 'position'
                            })

            elif event_type == 'LogPlayerKillV2':
                if 'victim' in event and 'name' in event['victim'] and event['victim']['name'] == player:
                    kill_events.append({
                        'x': event['victim']['location']['x'], # Adiciona a posição da morte
                        'y': event['victim']['location']['y'],
                        'time': event_time, # Usando o tempo normalizado
                        'type': 'kill_break'
                    })

        # Combina eventos de posição e morte e ordena por tempo
        all_events = sorted(loc_data + kill_events, key=lambda x: x.get('time', 0))

        final_path = []
        last_death_location = None

        for event in all_events:
            if event['type'] == 'kill_break':
                # Adiciona o kill_break (agora com a posição da morte)
                final_path.append(event)
                last_death_location = (event['x'], event['y']) # Armazena a posição da morte
                # print(f"DEBUG: Kill_break detectado para '{player}' em {event['time']:.2f}s em ({event['x']:.2f}, {event['y']:.2f}).")
            else: # É um evento de posição
                # Se houve uma morte registrada e esta é a primeira posição após,
                # marcamos como 'after_death_position'.
                # Caso contrário, é uma posição normal.
                if last_death_location:
                    event['type'] = 'after_death_position'
                    last_death_location = None # Resetamos, pois já processamos a primeira posição após a morte
                else:
                    event['type'] = 'position'
                final_path.append(event)

        # print(f"DEBUG: getPlayerXY encontrou {len(final_path)} pontos para o jogador '{player if player else 'TODOS'}'")
        return final_path

    def getFlightFit(self):
        """
        Calcula a linha de melhor ajuste para a trajetória de voo inicial.
        Retorna a inclinação (m) e a interceptação (c) da linha y = mx + c.
        """
        flight_loc_data = [data for data in self.telemetry if data.get('_T') == 'LogPlayerPosition']
        loc_for_flight = []
        for data in flight_loc_data:
            if 'character' in data and 'location' in data['character']:
                elapsed_time = data.get('elapsedTime', 0)
                # Apenas considera pontos com tempo decorrido para o cálculo do voo
                if elapsed_time != 0:
                    loc_for_flight.append({
                        'x': data['character']['location']['x'],
                        'y': data['character']['location']['y'],
                        'time': elapsed_time
                    })
        loc = sorted(loc_for_flight, key=lambda x: x['time'])

        if not loc:
            print("Aviso: Não há dados de localização com tempo para calcular o ajuste de voo.")
            return 0, 0

        # Pega os primeiros pontos para determinar a linha de voo
        early_loc = [data for data in loc if data['time'] < 5] # Primeiros 5 segundos

        if not early_loc:
            print("Aviso: Não há dados de localização nos primeiros 5 segundos para calcular o ajuste de voo.")
            return 0, 0

        x = np.array([data['x'] for data in early_loc])
        y = np.array([data['y'] for data in early_loc])

        if len(x) < 2:
            print("Aviso: Poucos pontos de dados para calcular a linha de voo. Necessário pelo menos 2 pontos.")
            return 0, 0

        # Calcula a linha de melhor ajuste usando mínimos quadrados
        A = np.vstack([x, np.ones(len(x))]).T
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]
        return m, c

    def getKillsXY(self, killer=None, victim=None):
        """
        Obtém as coordenadas X e Y dos eventos de morte (LogPlayerKillV2),
        opcionalmente filtrando por assassino e/ou vítima.
        Retorna uma lista de dicionários com 'x' e 'y' da vítima.
        """
        kills_data = [data for data in self.telemetry if data.get('_T') == 'LogPlayerKillV2']
        if killer:
            kills_data = [data for data in kills_data if 'killer' in data and 'name' in data['killer'] and data['killer']['name']==killer]
        if victim:
            kills_data = [data for data in kills_data if 'victim' in data and 'name' in data['victim'] and data['victim']['name']==victim]

        kills = [{'x':data['victim']['location']['x'],
                  'y':data['victim']['location']['y'],
                  'victim_name': data['victim']['name'] if 'victim' in data and 'name' in data['victim'] else 'Unknown'} # Adiciona o nome da vítima
                 for data in kills_data if 'victim' in data and 'location' in data['victim']]
        return kills

    def getItemFindsXY(self, player=None):
        """
        Obtém as coordenadas X e Y dos eventos de coleta de item (LogItemPickup),
        opcionalmente filtrando por um jogador específico.
        Retorna uma lista de dicionários com 'x' e 'y' do item.
        """
        items_data = [data for data in self.telemetry if data.get('_T') == 'LogItemPickup']
        if player:
            items_data = [data for data in items_data if 'character' in data and 'name' in data['character'] and data['character']['name']==player]
        item_finds = [{'x' : data['character']['location']['x'],
                       'y' : data['character']['location']['y']}
                      for data in items_data if 'character' in data and 'location' in data['character']]
        return item_finds

    def getMagneticXY(self):
        """
        Obtém as coordenadas X e Y e o raio dos eventos de zona segura (LogGameStatePeriodic).
        Retorna uma lista de dicionários com 'x', 'y' e 'r'.

        AJUSTE: Revertido para a lógica original para evitar múltiplas zonas redundantes.
        """
        gamestate_data = [data for data in self.telemetry if data.get('_T') == 'LogGameStatePeriodic']
        magnetic_raw = [{'x':data['gameState']['safetyZonePosition']['x'],
                         'y':data['gameState']['safetyZonePosition']['y'],
                         'r':data['gameState']['safetyZoneRadius']}
                        for data in gamestate_data
                        if 'gameState' in data and
                           'safetyZonePosition' in data['gameState'] and
                           'safetyZoneRadius' in data['gameState']]
        # Lógica original para remover duplicatas e manter apenas as zonas que aparecem mais de uma vez
        magnetic = [dict(t) for t in set([tuple(data.items()) for data in magnetic_raw if magnetic_raw.count(data) > 1])]
        return magnetic

    def getCarePackagesXY(self):
        """
        Obtém as coordenadas X e Y dos eventos de pacote de ajuda (LogCarePackageLand, LogCarePackageSpawn).
        Retorna uma lista de dicionários com 'x' e 'y'.
        """
        care_package_events = [
            data for data in self.telemetry
            if data.get('_T') in ['LogCarePackageLand', 'LogCarePackageSpawn']
        ]

        care_packages_loc = []
        for data in care_package_events:
            if 'itemPackage' in data and 'location' in data['itemPackage']:
                care_packages_loc.append({
                    'x': data['itemPackage']['location']['x'],
                    'y': data['itemPackage']['location']['y']
                })
        return care_packages_loc
    
    def getEmergencyPickupsXY(self, players_to_track_names: set):
        """
        Obtém as coordenadas X e Y de eventos de Emergency Pickup.
        Filtra para incluir apenas pickups feitos por jogadores da lista 'players_to_track_names'.
        Retorna uma lista de dicionários com 'x' e 'y'.
        """
        emergency_pickup_events = [
            data for data in self.telemetry
            if data.get('_T') == 'LogItemPickup' and
               data.get('item', {}).get('itemId') == 'Item_EmergencyPickup_C' and
               data.get('character', {}).get('name') in players_to_track_names # Garante que é um pickup do jogador/time rastreado
        ]

        pickup_locations = []
        for event in emergency_pickup_events:
            if 'character' in event and 'location' in event['character']:
                pickup_locations.append({
                    'x': event['character']['location']['x'],
                    'y': event['character']['location']['y']
                })
        return pickup_locations

# ================================================================
# CONTEÚDO COMPLETO DE SEU map_editor.py
# ================================================================
class MapEditor:
    def __init__(self, mapFile, mapSize):
        """
        Inicializa o MapEditor com o arquivo de imagem do mapa e o tamanho do mapa em unidades do jogo.
        Calcula o fator de reescalonamento para converter coordenadas do jogo para pixels da imagem.
        """
        try:
            self.img = Image.open(mapFile)
            self.rescale = self.img.size[0] / mapSize # Corrigido para .size[0]
        except FileNotFoundError:
            raise FileNotFoundError(f"Arquivo de mapa não encontrado: {mapFile}")
        except Exception as e:
            raise Exception(f"Erro ao carregar ou processar imagem do mapa {mapFile}: {e}")


    def draw_watermark(self, image_path, opacity, position='top_right', padding=(10, 10)):
        """Desenha uma imagem como marca d'água com uma dada opacidade."""
        try:
            watermark_img = Image.open(image_path).convert("RGBA")
        except FileNotFoundError as e:
            print(f"Erro ao abrir imagem da marca d'água: {e}")
            return

        # Aplica a opacidade
        watermark_img = self._set_opacity(watermark_img, opacity)

        img_width, img_height = self.img.size
        wm_width, wm_height = watermark_img.size
        padding_x, padding_y = padding

        if position == 'top_right':
            # Posição para a imagem única no canto superior direito
            wm_x = img_width - wm_width - padding_x
            wm_y = padding_y
        else:
            print(f"Posição '{position}' não suportada para marca d'água.")
            return

        self.img.paste(watermark_img, (wm_x, wm_y), watermark_img)

    def _set_opacity(self, img, opacity):
        """Define a opacidade de uma imagem (0-1)."""
        img = img.convert("RGBA")
        datas = img.getdata()

        new_data = []
        for item in datas:
            new_alpha = int(item[-1] * opacity)
            new_data.append((item[:-1] + (new_alpha,)))
        img.putdata(new_data)
        return img

    def draw_flight(self, fit, color, width):
        """
        Desenha a linha de voo no mapa.
        'fit' é uma tupla (m, c) da equação da linha y = mx + c.
        """
        m = fit[0]
        c = fit[1] * self.rescale # Reescalona a interceptação 'c' para as coordenadas da imagem
        size = self.img.size[0] # Largura/altura da imagem

        # Calcula os pontos de início e fim da linha de voo na borda da imagem
        # Garante que a linha se estenda por toda a largura do mapa
        x1 = 0
        y1 = m * x1 + c

        x2 = size
        y2 = m * x2 + c

        # Ajusta os pontos para garantir que estejam dentro dos limites da imagem
        points = []
        # Adiciona pontos que estão nas bordas X
        if 0 <= y1 <= size:
            points.append((x1, y1))
        if 0 <= y2 <= size:
            points.append((x2, y2))

        # Adiciona pontos que estão nas bordas Y (se a linha cruzar)
        if m != 0: # Evita divisão por zero para linhas horizontais
            x_at_y0 = (0 - c) / m
            if 0 <= x_at_y0 <= size:
                points.append((x_at_y0, 0))
            x_at_ysize = (size - c) / m
            if 0 <= x_at_ysize <= size:
                points.append((x_at_ysize, size))

        # Remove duplicatas e ordena os pontos para desenhar a linha corretamente
        # Converta as coordenadas para int aqui antes de desenhar
        int_points = []
        for p in points:
            int_points.append((int(p[0]), int(p[1])))

        # Remove duplicatas e ordena os pontos para desenhar a linha corretamente
        int_points = sorted(list(set(int_points)))


        try:
            draw = ImageDraw.Draw(self.img, 'RGBA')
            if len(int_points) >= 2:
                # Desenha a linha conectando os dois pontos mais extremos
                draw.line(int_points, fill=color['outline'], width=width)
            else:
                print("Aviso: Poucos pontos válidos para desenhar a linha de voo.")
        except Exception as e:
            print(f"Erro ao desenhar linha de voo: {e}")

    def draw_magnetic(self, xy_magnetic):
        """
        Desenha os círculos das zonas magnéticas no mapa.
        'xy_magnetic' é uma lista de dicionários com 'x', 'y' (centro) e 'r' (raio).
        """
        for data in xy_magnetic:
            x = int(data['x'] * self.rescale)
            y = int(data['y'] * self.rescale)
            r = int(data['r'] * self.rescale)
            try:
                draw = ImageDraw.Draw(self.img, 'RGBA')
                # Desenha uma elipse (que será um círculo se x e y forem iguais)
                draw.ellipse((x-r, y-r, x+r, y+r), outline=(255,255,255,255), fill=((255,255,255,0)), width=5)
            except Exception as e:
                print(f"Erro ao desenhar zona magnética: {e}")

    def draw_flags(self, xy_type, color, flagSize):
        """
        Desenha "bandeiras" (círculos) em locais específicos no mapa.
        'xy_type' é uma lista de dicionários com 'x' e 'y'.
        'color' é um dicionário com 'outline' e 'fill' (RGBA).
        'flagSize' é o diâmetro do círculo em pixels.
        """
        for data in xy_type:
            x = int(data['x'] * self.rescale)
            y = int(data['y'] * self.rescale)
            offset = (flagSize - 1) / 2 # Metade do tamanho para centralizar
            try:
                draw = ImageDraw.Draw(self.img, 'RGBA')
                # As coordenadas de ellipse devem ser inteiras
                draw.ellipse((int(x - offset), int(y - offset), int(x + offset), int(y + offset)), outline=color['outline'], fill=color['fill'])
            except Exception as e:
                print(f"Erro ao desenhar bandeira: {e}")

    def draw_icon(self, xy_data, icon_path, icon_size, tint_color: tuple = None):
        """
        Desenha ícones de imagem em locais específicos no mapa.
        'xy_data' é uma lista de dicionários com 'x' e 'y'.
        'icon_path' é o caminho para o arquivo da imagem do ícone.
        'icon_size' é o tamanho desejado (largura/altura) do ícone em pixels.
        'tint_color' é uma tupla RGBA opcional para colorir o ícone.
        """
        try:
            icon_img = Image.open(icon_path).convert("RGBA")
            # Redimensiona o ícone para o tamanho desejado
            icon_img = icon_img.resize((icon_size, icon_size), Image.Resampling.LANCZOS)

            # --- NOVA LÓGICA: Aplicar cor ao ícone ---
            if tint_color:
                # Cria uma imagem de cor sólida com a cor e alfa desejados
                color_layer = Image.new('RGBA', icon_img.size, tint_color)
                # Combina a camada de cor com o ícone, usando o canal alfa do ícone
                # para determinar onde a cor deve ser aplicada.
                # A imagem original (preta no caso de morte.png) será colorida.
                # Onde o ícone é transparente, a cor não será aplicada.
                icon_img = Image.alpha_composite(Image.new('RGBA', icon_img.size, (0, 0, 0, 0)), icon_img) # Garante fundo transparente
                icon_img = Image.composite(color_layer, icon_img, icon_img.split()[-1]) # Usa o alfa do ícone original como máscara
            # --- FIM DA NOVA LÓGICA ---

        except FileNotFoundError:
            print(f"Aviso: Ícone não encontrado em {icon_path}. Pulando desenho do ícone.")
            return
        except Exception as e:
            print(f"Erro ao carregar, redimensionar ou colorir ícone {icon_path}: {e}")
            return

        for data in xy_data:
            x = int(data['x'] * self.rescale)
            y = int(data['y'] * self.rescale)

            # Calcula o offset para centralizar o ícone
            offset_x = icon_size // 2
            offset_y = icon_size // 2

            # Posição de colagem (canto superior esquerdo)
            paste_x = x - offset_x
            paste_y = y - offset_y

            # Garante que as coordenadas de colagem estejam dentro dos limites da imagem
            paste_x = max(0, min(paste_x, self.img.width - icon_size))
            paste_y = max(0, min(paste_y, self.img.height - icon_size))

            try:
                self.img.paste(icon_img, (paste_x, paste_y), icon_img)

            except Exception as e:
                print(f"Erro ao desenhar ícone em ({x}, {y}) do tipo {icon_path}: {e}")


    def draw_path(self, xy_path, initial_color, after_death_color, width):
        """
        Desenha o trajeto de um jogador, mas agora RETORNA as coordenadas
        de ressurgimento em vez de desenhar um 'X'.
        """
        draw = ImageDraw.Draw(self.img, 'RGBA')
        current_segment = []
        current_color = initial_color
        last_death_pos_px = None # Posição da morte em pixels

        min_distance_for_new_segment_sq = (int(500 * self.rescale)) ** 2

        death_markers = []
        spawn_markers = []

        for i, data in enumerate(xy_path):
            x_px = data['x'] * self.rescale
            y_px = data['y'] * self.rescale
            current_pos_px = (int(x_px), int(y_px))

            if data['type'] == 'kill_break':
                if len(current_segment) >= 2:
                    filtered_coords = []
                    if current_segment:
                        filtered_coords.append(current_segment[0])
                        tolerance = 0.2
                        for j in range(1, len(current_segment)):
                            last_x_f, last_y_f = filtered_coords[-1]
                            current_x_s, current_y_s = current_segment[j]
                            distance_sq = (current_x_s - last_x_f)**2 + (current_y_s - last_y_f)**2
                            if distance_sq > tolerance**2:
                                # CORREÇÃO AQUI: Adiciona a tupla (x, y)
                                filtered_coords.append((current_x_s, current_y_s))

                        if len(filtered_coords) >= 2:
                            draw.line(filtered_coords, fill=current_color['outline'], width=width)
                        # else:
                            # print(f"Aviso: Poucos pontos válidos para desenhar o segmento do trajeto após a filtragem (antes da morte).")

                current_segment = []
                current_color = after_death_color
                last_death_pos_px = current_pos_px
                death_markers.append(current_pos_px) # Adiciona marcador de morte (X preto)
                continue

            if data['type'] == 'position' or data['type'] == 'after_death_position':
                if last_death_pos_px:
                    distance_from_death_sq = (current_pos_px[0] - last_death_pos_px[0])**2 + \
                                             (current_pos_px[1] - last_death_pos_px[1])**2

                    if distance_from_death_sq >= min_distance_for_new_segment_sq:
                        current_segment.append(current_pos_px)
                        # Adiciona as coordenadas do JOGO (não de pixels) à lista
                        spawn_markers.append({'x': data['x'], 'y': data['y']})
                        last_death_pos_px = None
                    else:
                        pass
                else:
                    current_segment.append(current_pos_px)

        if len(current_segment) >= 2:
            filtered_coords = []
            if current_segment:
                filtered_coords.append(current_segment[0])
                tolerance = 0.4
                for j in range(1, len(current_segment)):
                    last_x_f, last_y_f = filtered_coords[-1]
                    current_x_s, current_y_s = current_segment[j]
                    distance_sq = (current_x_s - last_x_f)**2 + (current_y_s - last_y_f)**2
                    if distance_sq > tolerance**2:
                        # CORREÇÃO AQUI: Adiciona a tupla (x, y)
                        filtered_coords.append((current_x_s, current_y_s))

                if len(filtered_coords) >= 2:
                    draw.line(filtered_coords, fill=current_color['outline'], width=width)
                # else:
                    # print(f"Aviso: Poucos pontos válidos para desenhar o último segmento do trajeto após a filtragem.")

        # REMOVIDO: A marcação de morte com 'X' preto será feita por draw_icon com 'morte.png'
        # Isso centraliza a responsabilidade da marcação de morte de jogadores rastreados no _process_and_save_map

        return spawn_markers


    def save_map(self, fileName):
        """
        Salva a imagem do mapa modificada em um arquivo.
        """
        try:
            self.img.save(fileName)
        except Exception as e:
            print(f"Erro ao salvar mapa: {e}")

    def draw_legend(self, elements_info, padding=20, item_spacing=15, default_icon_diameter=20, font_size=16, position='top_left'):
        """
        Desenha uma legenda no mapa com base nos elementos fornecidos.
        A 'position' pode ser 'top_left' ou 'bottom_right'.
        """
        draw = ImageDraw.Draw(self.img, 'RGBA')

        try:
            font = ImageFont.truetype("fonts/arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()
            print("Aviso: Fonte 'arial.ttf' não encontrada no caminho especificado. Usando fonte padrão.")

        max_text_width = 0
        total_height = 0
        for item in elements_info:
            label = item['label']
            icon_diameter = item.get('icon_diameter', default_icon_diameter)
            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            # Usar max(icon_diameter, text_bbox[3] - text_bbox[1]) para garantir altura suficiente
            text_height = text_bbox[3] - text_bbox[1]
            current_item_width = icon_diameter + 20 + text_width
            if current_item_width > max_text_width:
                max_text_width = current_item_width
            total_height += max(icon_diameter, text_height) + item_spacing

        if elements_info:
            total_height -= item_spacing # Remove o espaçamento extra do último item

        # Calcula a posição do fundo da legenda
        if position == 'top_left':
            background_x1 = int(padding - 10)
            background_y1 = int(padding - 10)
            background_x2 = int(padding + max_text_width + 10)
            background_y2 = int(padding + total_height + 10)
        elif position == 'bottom_right':
            background_x2 = self.img.width - (padding - 10)
            background_y2 = self.img.height - (padding - 10)
            background_x1 = background_x2 - (max_text_width + 20)
            background_y1 = background_y2 - (total_height + 20)
        else: # Default para top_left
            background_x1 = int(padding - 10)
            background_y1 = int(padding - 10)
            background_x2 = int(padding + max_text_width + 10)
            background_y2 = int(padding + total_height + 10)

        draw.rectangle([background_x1, background_y1, background_x2, background_y2], fill=(0, 0, 0, 128))

        current_y = background_y1 + 10 # Começa a desenhar os itens após o padding do fundo
        for item in elements_info:
            label = item['label']
            color_dict = item['color']
            item_type = item['type']
            icon_diameter = int(item.get('icon_diameter', default_icon_diameter))
            
            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_height_actual = text_bbox[3] - text_bbox[1]
            text_offset_y = (icon_diameter - text_height_actual) / 2 # Centraliza o texto verticalmente com o ícone

            icon_x_start = int(background_x1 + 10) # Alinha ícones com o padding do fundo
            icon_y_start = int(current_y)

            if item_type == 'path':
                line_width = max(2, int(icon_diameter / 10))
                # Desenha um segmento de linha para representar o caminho
                draw.line([(icon_x_start, int(icon_y_start + icon_diameter / 2)),
                           (int(icon_x_start + icon_diameter), int(icon_y_start + icon_diameter / 2))],
                          fill=color_dict['outline'], width=line_width)
            elif item_type == 'flag':
                draw.ellipse((icon_x_start, icon_y_start, icon_x_start + icon_diameter, icon_y_start + icon_diameter),
                             outline=color_dict['outline'], fill=color_dict['fill'])
            elif item_type == 'ellipse':
                ellipse_width = max(2, int(icon_diameter / 20))
                draw.ellipse((icon_x_start, icon_y_start, icon_x_start + icon_diameter, icon_y_start + icon_diameter),
                             outline=color_dict['outline'], fill=(0,0,0,0), width=ellipse_width)
            elif item_type == 'x_marker': # Mantido caso ainda seja usado em outro lugar, mas o ícone 'morte' é preferido
                line_width = max(2, int(icon_diameter / 10))
                center_x = icon_x_start + icon_diameter / 2
                center_y = icon_y_start + icon_diameter / 2
                marker_half_size = icon_diameter / 2
                draw.line([(int(center_x - marker_half_size), int(center_y - marker_half_size)),
                           int(center_x + marker_half_size), int(center_y + marker_half_size)],
                          fill=color_dict['outline'], width=line_width)
                draw.line([(int(center_x + marker_half_size), int(center_y - marker_half_size)),
                           int(center_x - marker_half_size), int(center_y + marker_half_size)],
                          fill=color_dict['outline'], width=line_width)
            elif item_type == 'image_icon':
                icon_path = item.get('icon_path')
                tint_color_for_legend = item.get('tracked_player_death_color') # Pega a cor de tint se existir para ícones de morte

                if icon_path:
                    try:
                        legend_icon_img = Image.open(icon_path).convert("RGBA")
                        legend_icon_img = legend_icon_img.resize((icon_diameter, icon_diameter), Image.Resampling.LANCZOS)

                        if tint_color_for_legend:
                            color_layer_legend = Image.new('RGBA', legend_icon_img.size, tint_color_for_legend)
                            legend_icon_img = Image.alpha_composite(Image.new('RGBA', legend_icon_img.size, (0, 0, 0, 0)), legend_icon_img)
                            legend_icon_img = Image.composite(color_layer_legend, legend_icon_img, legend_icon_img.split()[-1])

                        self.img.paste(legend_icon_img, (icon_x_start, icon_y_start), legend_icon_img)
                    except FileNotFoundError:
                        print(f"Aviso: Ícone da legenda não encontrado em {icon_path}.")
                    except Exception as e:
                        print(f"Erro ao desenhar ícone da legenda {icon_path}: {e}")
                else:
                    print(f"Aviso: 'icon_path' ausente para item da legenda do tipo 'image_icon'.")

            text_x = int(icon_x_start + icon_diameter + 20)
            text_y = int(current_y + text_offset_y)
            draw.text((text_x, text_y), label, fill=color_dict['outline'], font=font)
            current_y += max(icon_diameter, text_height_actual) + item_spacing

    def draw_player_legend(self, players_info, padding=20, item_spacing=15, default_icon_diameter=20, font_size=16):
        """
        Desenha uma legenda específica para os jogadores rastreados no canto inferior direito do mapa.
        'players_info' é uma lista de dicionários com 'name' e 'color' (tupla RGBA).
        """
        draw = ImageDraw.Draw(self.img, 'RGBA')

        try:
            font = ImageFont.truetype("fonts/arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()
            print("Aviso: Fonte 'arial.ttf' não encontrada no caminho especificado. Usando fonte padrão.")

        max_text_width = 0
        total_height = 0
        for player in players_info:
            label = player['name']
            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            current_item_width = default_icon_diameter + 20 + text_width
            if current_item_width > max_text_width:
                max_text_width = current_item_width
            total_height += max(default_icon_diameter, text_height) + item_spacing

        if players_info:
            total_height -= item_spacing # Remove o espaçamento extra do último item

        # Calcula a posição do fundo da legenda no canto inferior direito
        background_x2 = self.img.width - (padding - 10)
        background_y2 = self.img.height - (padding - 10)
        background_x1 = background_x2 - (max_text_width + 20)
        background_y1 = background_y2 - (total_height + 20)

        draw.rectangle([background_x1, background_y1, background_x2, background_y2], fill=(0, 0, 0, 128))

        current_y = background_y1 + 10 # Começa a desenhar os itens após o padding do fundo
        for player in players_info:
            label = player['name']
            player_color = player['color'] # Isso deve ser a tupla RGBA para o contorno do trajeto

            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_height_actual = text_bbox[3] - text_bbox[1]
            text_offset_y = (default_icon_diameter - text_height_actual) / 2

            icon_x_start = int(background_x1 + 10)
            icon_y_start = int(current_y)

            # Desenha um segmento de linha para representar a cor do trajeto do jogador
            line_width = max(2, int(default_icon_diameter / 10))
            draw.line([(icon_x_start, int(icon_y_start + default_icon_diameter / 2)),
                       (int(icon_x_start + default_icon_diameter), int(icon_y_start + default_icon_diameter / 2))],
                      fill=player_color, width=line_width)

            text_x = int(icon_x_start + default_icon_diameter + 20)
            text_y = int(current_y + text_offset_y)
            draw.text((text_x, text_y), label, fill=player_color, font=font) # Cor do texto é a mesma do trajeto
            current_y += max(default_icon_diameter, text_height_actual) + item_spacing

# ==================================
MAPA_TRADUZIDO = {
    "Desert_Main": "miramar.webp",
    "Erangel_Main": "erangel.webp",
    "Savage_Main": "sanhok.webp",
    "DihorOtok_Main": "vikendi.webp",
    "Baltic_Main": "erangel.webp",
    "Summerland_Main": "paramo.webp",
    "Neon_Main": "rondo.webp",
    "Tiger_Main": "taego.webp",
    "Deston_Main": "deston.webp",
    "Chimera_Main": "CampodeTreinamento.webp",
    "Kiki_Main": "deston.webp", # Kiki_Main mapeia para Deston.webp, como no original
}

MAPA_NOMES = {
    "Desert_Main": "Miramar",
    "Erangel_Main": "Erangel",
    "Savage_Main": "Sanhok",
    "DihorOtok_Main": "Vikendi",
    "Baltic_Main": "Erangel Remasterizado",
    "Summerland_Main": "Paramo",
    "Neon_Main": "Rondo",
    "Tiger_Main": "Taego",
    "Deston_Main": "Deston",
    "Chimera_Main": "Campo de Treinamento",
    "Kiki_Main": "Rondo", # Mantém a consistência
}

color = {
    'red' : {'outline' : (255, 0, 0 , 255), 'fill' : (255, 0, 0, 255)},
    'blue' : {'outline' : (1, 1, 198, 255), 'fill' : (1, 1, 198, 100)},
    'white' : {'outline' : (255, 255, 255, 255), 'fill' : (255, 255, 255, 100)},
    'orange' : {'outline' : (255, 165, 0, 255), 'fill' : (255, 165, 0, 100)},
    'green' : {'outline' : (0, 255, 0, 255), 'fill' : (0, 255, 0, 150)},
    'purple' : {'outline' : (128, 0, 128, 255), 'fill' : (128, 0, 128, 70)},
    'cyan' : {'outline' : (0, 255, 255, 255), 'fill' : (0, 255, 255, 120)},
    'yellow' : {'outline' : (255, 255, 0, 255), 'fill' : (255, 255, 0, 200)},
    'black' : {'outline' : (0, 0, 0, 255), 'fill' : (0, 0, 0, 255)},
    'magenta' : {'outline' : (255, 0, 255, 255), 'fill' : (255, 0, 255, 120)}
}

class PUBGTelmetry(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.PUBG_API_KEY = os.getenv('PUBG_API_KEY')
        if not self.PUBG_API_KEY:
            print("AVISO: PUBG_API_KEY não encontrada no arquivo .env. O download da telemetria pode falhar.")

    async def _download_telemetry(self, match_id: str):
        telemetry_filename = f"telemetry/{match_id}.json"
        os.makedirs('telemetry', exist_ok=True)

        async with aiohttp.ClientSession() as session:
            try:
                match_api_url = f"https://api.pubg.com/shards/steam/matches/{match_id}"
                headers = {
                    "Accept": "application/vnd.api+json",
                    "Authorization": f"Bearer {self.PUBG_API_KEY}"
                }
                
                async with session.get(match_api_url, headers=headers) as response:
                    response.raise_for_status()
                    match_data = await response.json()

                telemetry_url = None
                for asset in match_data['included']:
                    if asset['type'] == 'asset' and 'URL' in asset['attributes']:
                        telemetry_url = asset['attributes']['URL']
                        break
                if not telemetry_url:
                    print(f"Erro: Não foi possível encontrar a URL da telemetria para a partida `{match_id}`.")
                    return None
                
                async with session.get(telemetry_url) as telemetry_response:
                    telemetry_response.raise_for_status()
                    with open(telemetry_filename, 'wb') as f:
                        while True:
                            chunk = await telemetry_response.content.read(1024)
                            if not chunk:
                                break
                            f.write(chunk)
                
                print(f"Telemetria baixada e salva como `{telemetry_filename}`.")
                return telemetry_filename
            
            except aiohttp.ClientError as err:
                print(f"Não consegui encontrar a sua telemetria, verifique o Match ID e tente novamente.")
                return None
            except Exception as err:
                print(f"Ocorreu um erro inesperado durante o download da telemetria. Erro: `{err}`")
                return None

    # --- COMANDO /telemetria ---
    @app_commands.command(name="telemetria", description="Gera uma imagem com a telemetria em uma partida específica do PUBG.")
    @is_rank_channel_check
    @app_commands.describe(
        nickname="O nickname do jogador a ser rastreado.",
        match_id="O ID da partida (Match ID) do PUBG.",
        time="Se 'Sim', rastreia o time inteiro do jogador. Opcional, padrão 'Nao'." 
    )
    @app_commands.choices(
        time=[
            app_commands.Choice(name="Sim", value="Sim"),
            app_commands.Choice(name="Nao", value="Nao")
        ]
    )
    async def trajeto(self, interaction: discord.Interaction, nickname: str, match_id: str, time: str = "Nao"):
        await interaction.response.defer(thinking=True, ephemeral=True)

        track_team = (time == "Sim")
        telemetry_filename = None
        output_filename = None

        try:
            await interaction.edit_original_response(content="Aguarde enquanto estamos renderizando a trajetória...")
            await asyncio.sleep(2) 
            await interaction.edit_original_response(content="Renderizando a imagem em alta resolução ...")
            await asyncio.sleep(3)
            await interaction.edit_original_response(content="Estamos quase lá.. O processamento levará até 60 segundos, mas estamos agilizando ao máximo.")

            telemetry_filename = await self._download_telemetry(match_id)
            
            if not telemetry_filename:
                await interaction.edit_original_response(content="Não consegui encontrar a sua telemetria, verifique o Match ID e tente novamente.")
                return

            tele = TeleProcessor(telemetry_filename)

            map_name_raw = None
            for event in tele.telemetry:
                if event.get('_T') == 'LogMatchStart':
                    map_name_raw = event.get('mapName')
                    break
            if not map_name_raw:
                for event in tele.telemetry:
                    if event.get('_T') == 'LogPlayerCreate' and 'character' in event:
                        map_name_raw = event['character'].get('mapName')
                        if map_name_raw:
                            break
                if not map_name_raw:
                    for event in tele.telemetry:
                        if event.get('_T') == 'LogPlayerPosition' and 'character' in event:
                            map_name_raw = event['character'].get('mapName')
                            if map_name_raw:
                                break
                if not map_name_raw:
                    print("AVISO: Não foi possível determinar o nome do mapa da telemetria. Usando 'Desert_Main' como padrão.")
                    map_name_raw = "Desert_Main"

            map_display_name = MAPA_NOMES.get(map_name_raw, map_name_raw)
            map_image_file = MAPA_TRADUZIDO.get(map_name_raw, "miramar.webp")
            fixed_map_size = 816001

            players_to_track = []
            team_member_names = []

            if track_team:
                player_team_id = tele.get_player_team_id(nickname)
                if player_team_id is None:
                    await interaction.edit_original_response(content=f"Erro: Não foi possível encontrar o time do jogador `{nickname}` nesta partida. Verifique se o nickname está correto ou tente sem a opção de time.")
                    return

                team_members = tele.get_team_members(player_team_id)
                if nickname in team_members:
                    team_members.remove(nickname)
                    team_members.insert(0, nickname)
                else:
                    team_members.insert(0, nickname)

                for member_name in team_members:
                    member_xy_loc = tele.getPlayerXY(player=member_name)
                    if member_xy_loc:
                        players_to_track.append({'name': member_name, 'xy_loc': member_xy_loc})
                        team_member_names.append(member_name)
                    else:
                        print(f"Aviso: Nenhum dado de localização encontrado para o membro do time '{member_name}'.")

                if not players_to_track:
                    await interaction.edit_original_response(content=f"Não foram encontrados dados de telemetria para o time do jogador `{nickname}`.")
                    return
            else:
                player_xy_loc = tele.getPlayerXY(player=nickname)
                if not player_xy_loc:
                    await interaction.edit_original_response(content=f"Não foram encontrados dados de telemetria para o jogador `{nickname}` nesta partida.")
                    return
                players_to_track.append({'name': nickname, 'xy_loc': player_xy_loc})
                team_member_names.append(nickname)

            xy_kills = tele.getKillsXY()
            xy_magnetic = tele.getMagneticXY()
            fit_flight = tele.getFlightFit()
            xy_care_packages = tele.getCarePackagesXY()

            func_to_run = functools.partial(
                _process_and_save_map,
                map_image_file=map_image_file,
                fixed_map_size=fixed_map_size,
                xy_kills=xy_kills,
                players_to_track=players_to_track,
                xy_magnetic=xy_magnetic,
                fit_flight=fit_flight,
                xy_care_packages=xy_care_packages,
                color=color,
                main_nickname=nickname,
                team_member_names=team_member_names,
                match_id=match_id,
                map_name_raw=map_name_raw,
                tele=tele
            )

            output_filename = await self.bot.loop.run_in_executor(None, func_to_run)

            if not output_filename:
                await interaction.edit_original_response(content=f"Ocorreu um erro ao gerar a imagem do mapa. Por favor, tente novamente mais tarde.")
                return

            final_message_content = f"Telemetria para o(s) jogador(es): **{', '.join(team_member_names)}** no mapa **{map_display_name}**:"

            if not players_to_track or not any(d['type'] in ['position', 'after_death_position'] for d in players_to_track[0]['xy_loc']):
                final_message_content += "\n\nAviso: Não foram encontrados dados de localização para o jogador principal nesta partida após o tempo 0."

            await interaction.edit_original_response(
                content=final_message_content,
                attachments=[discord.File(output_filename)]
            )
        except FileNotFoundError as err:
            await interaction.edit_original_response(content=f"Erro: Arquivo de mapa ou telemetria não encontrado. Verifique os caminhos: `{err}`")
            print(f"Erro de Arquivo: {err}")
        except Exception as err:
            await interaction.edit_original_response(content=f"Ocorreu um erro inesperado durante o processamento. Por favor, tente novamente mais tarde. Erro: `{err}`")
            print(f"Erro Inesperado: {err}")
        finally:
            print("Aguardando 5 minutos antes de remover os arquivos temporários...")
            await asyncio.sleep(300)

            if telemetry_filename and os.path.exists(telemetry_filename):
                try:
                    os.remove(telemetry_filename)
                    print(f"Arquivo de telemetria temporário removido: {telemetry_filename}")
                except Exception as err:
                    print(f"Erro ao remover arquivo de telemetria temporário: {err}")
            if output_filename and os.path.exists(output_filename):
                try:
                    os.remove(output_filename)
                    print(f"Arquivo de imagem temporário removido: {output_filename}")
                except Exception as err:
                    print(f"Erro ao remover arquivo de imagem temporário: {err}")

# Cores adicionais para os membros do time (totalmente diferentes)
TEAM_MEMBER_COLORS = [
    (200, 0, 200, 255),      # Roxo Magenta
    (255, 200, 0, 255),      # Amarelo puro
    (0, 200, 200, 255),      # Ciano turquesa
    (150, 75, 0, 255),       # Marrom
    (100, 0, 255, 255),      # Roxo azulado
    (255, 100, 100, 255),    # Rosa salmão
    (150, 150, 150, 255),    # Cinza
    (255, 0, 100, 255),      # Rosa choque
    (100, 50, 0, 255),       # Marrom escuro
]


def _process_and_save_map(map_image_file, fixed_map_size, xy_kills, players_to_track, xy_magnetic,
                           fit_flight, xy_care_packages, color, main_nickname, team_member_names, match_id, map_name_raw,
                           tele): # Removidos os argumentos de padding da legenda aqui
    """
    Função síncrona para processar e salvar o mapa.
    Destinada a ser executada em um executor para evitar bloquear o loop de eventos.
    Agora aceita uma lista de jogadores para rastrear.
    """
    try:
        start_img = time.time()
        output_dir = 'results'
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f'results/{main_nickname}_{match_id}_{map_name_raw}_trace.webp'

        editor = MapEditor(f'map_img/{map_image_file}', fixed_map_size)

        # Mapeia os nomes dos jogadores rastreados para facilitar a verificação
        tracked_player_names = {p['name'] for p in players_to_track}
        
        # Dicionário para armazenar as cores dos trajetos dos jogadores (para usar nos ícones de morte)
        player_path_colors = {}
        # Lista para armazenar as informações dos jogadores para a nova legenda
        player_legend_info = []

        # Preenche player_path_colors e player_legend_info antes de desenhar os caminhos
        color_index = 0
        for i, player_data in enumerate(players_to_track):
            player_name = player_data['name']
            if player_name == main_nickname:
                player_path_colors[player_name] = color['green']['outline'] # Cor inicial do trajeto do jogador principal
                player_legend_info.append({'name': player_name, 'color': color['green']['outline']})
            else:
                current_player_color_tuple = TEAM_MEMBER_COLORS[color_index % len(TEAM_MEMBER_COLORS)]
                player_path_colors[player_name] = current_player_color_tuple
                player_legend_info.append({'name': player_name, 'color': current_player_color_tuple})
                color_index += 1


        # Desenha as mortes de jogadores *NÃO* rastreados
        for kill in xy_kills:
            if kill['victim_name'] not in tracked_player_names:
                editor.draw_flags([kill], color['red'], 25) # Mortes de outros jogadores (círculo vermelho)

        # Desenha o trajeto de cada jogador e coleta as mortes e spawns
        death_icon_colors = {} # Para armazenar a cor do ícone de morte de cada jogador rastreado

        color_index = 0 # Reinicia para atribuir cores aos caminhos
        for i, player_data in enumerate(players_to_track):
            player_name = player_data['name']
            player_xy_loc = player_data['xy_loc']

            current_player_initial_color_dict = None
            current_player_after_death_color_dict = None

            if player_name == main_nickname:
                current_player_initial_color_dict = color['green']
                current_player_after_death_color_dict = color['green']
                death_icon_colors[player_name] = color['green']['outline'] # Cor do ícone de morte do jogador principal
            else:
                current_player_color_tuple = TEAM_MEMBER_COLORS[color_index % len(TEAM_MEMBER_COLORS)]
                current_player_initial_color_dict = {'outline': current_player_color_tuple, 'fill': current_player_color_tuple}
                current_player_after_death_color_dict = {'outline': current_player_color_tuple, 'fill': current_player_color_tuple} # Usar a mesma cor pós-morte para simplicidade do time
                death_icon_colors[player_name] = current_player_color_tuple # Cor do ícone de morte do membro do time
                color_index += 1

            # Desenha o trajeto e coleta spawn_locations para cada jogador
            spawn_locations = editor.draw_path(player_xy_loc, current_player_initial_color_dict, current_player_after_death_color_dict, 10)
            if spawn_locations:
                editor.draw_icon(spawn_locations, 'icons/revive.png', 200) # Desenha ícone de ressurgimento para cada um

        # Desenha os ícones de morte para TODOS os jogadores rastreados que morreram,
        # usando a cor do trajeto daquele jogador.
        for player_data in players_to_track:
            player_name = player_data['name']
            player_xy_loc = player_data['xy_loc']
            player_death_locations = []
            for event in player_xy_loc:
                if event['type'] == 'kill_break':
                    player_death_locations.append({'x': event['x'], 'y': event['y']})
            
            if player_death_locations:
                # Pega a cor do trajeto do jogador para tingir o ícone de morte
                tint_color_tuple = death_icon_colors.get(player_name, (255, 0, 0, 255)) # Padrão vermelho se não encontrar
                editor.draw_icon(player_death_locations, 'icons/morte.png', 100, tint_color=tint_color_tuple)


        editor.draw_magnetic(xy_magnetic)
        editor.draw_flight(fit_flight, color['white'], 10)
        editor.draw_icon(xy_care_packages, 'icons/drop.png', 100)

        # NOVO: Obtém e desenha os Emergency Pickups
        xy_emergency_pickups = tele.getEmergencyPickupsXY(tracked_player_names) # Passa o set de nomes rastreados
        if xy_emergency_pickups:
            editor.draw_icon(xy_emergency_pickups, 'icons/pickup.png', 130) # Use o tamanho adequado, 100 é um exemplo

        # --- Legenda Principal (canto superior esquerdo) ---
        main_legend_elements = [
            {'label': 'Morte do Time/Jogador', 'color': color['white'], 'type': 'image_icon', 'icon_path': 'icons/morte.png', 'icon_diameter': 100, 'tracked_player_death_color': (150, 150, 150, 255)}, # Cor padrão para o ícone na legenda
            {'label': 'Ressurgimento/revive', 'color': color['white'], 'type': 'image_icon', 'icon_path': 'icons/revive.png', 'icon_diameter': 100},
            {'label': 'Zonas Magnéticas', 'color': color['white'], 'type': 'ellipse', 'icon_diameter': 100},
            {'label': 'Trajeto de Voo', 'color': color['white'], 'type': 'path'},
            {'label': 'Coleta Emergencia', 'color': color['white'], 'type': 'image_icon', 'icon_path': 'icons/pickup.png', 'icon_diameter': 100},
            {'label': 'Airdrop', 'color': color['red'], 'type': 'image_icon', 'icon_path': 'icons/drop.png', 'icon_diameter': 100},
            {'label': 'Mortes (Outros Jogadores)', 'color': color['red'], 'type': 'flag', 'icon_diameter': 100},
        ]
        editor.draw_legend(main_legend_elements, padding=120, item_spacing=80,
                           default_icon_diameter=100, font_size=100, position='top_left')

        # --- Nova Legenda de Jogadores (canto inferior direito) ---
        if player_legend_info: # Desenha apenas se houver jogadores a serem rastreados
            editor.draw_player_legend(player_legend_info, padding=120, item_spacing=80,
                                      default_icon_diameter=100, font_size=100)
            
        # --- ADICIONAR AS LINHAS DA MARCA D'ÁGUA AQUI ---
        opacity = 0.5 # Defina o nível de transparência desejado (0.0 - 1.0)
        editor.draw_watermark('icons/test1.png', opacity, position='top_right', padding=(20, 20))
        # --- FIM DA ADIÇÃO ---

        editor.save_map(output_filename)

        delta_img = time.time() - start_img
        print('Image processing took: %f seconds.' % delta_img)
        return output_filename
    except Exception as err:
        print(f"Erro no processamento de imagem no executor: {err}")
        return None


async def setup(bot):
    await bot.add_cog(PUBGTelmetry(bot))