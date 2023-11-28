import requests
from bs4 import BeautifulSoup

import configparser
from telebot.apihelper import ApiTelegramException
import psutil

import telebot
from telebot import types
import telegraph

from datetime import datetime, timedelta
from time import sleep

import io
import schedule
import db
from loguru import logger


config = configparser.ConfigParser()
config.read('bot.conf')
logger.add(config['LOG']['LOG_PATH'])

TOKEN = config['NEWS']['TOKEN']
GROUP_LOG = int(config['NEWS']['NEWS_LOG'])
CHANNEL = int(config['NEWS']['NEWS_CHANNEL'])
CHANNEL_USERNAME = config['NEWS']['CHANNEL_USERNAME']
BOT_NAME = config['NEWS']['BOT_NAME']
BOT_USERNAME = config['NEWS']['BOT_USERNAME']
OWNER = int(config['NEWS']['OWNER_ID'])
OWNER_USERNAME = config['NEWS']['OWNER_USERNAME']
TELEGRAPH = config['NEWS']['TELEGRAPH_TOKEN']

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')


def get_news(limit=5):
    try:
        logger.info('Obtendo notícias...')
        url = 'https://ge.globo.com/futebol/brasileirao-serie-a/'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
        }

        response = requests.get(url, timeout=10, headers=headers)
        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.content, 'html.parser')
        post_sections = soup.find_all('div', {'class': 'bastian-feed-item'})

        news_list = []
        for section in post_sections[:limit]:
            logger.info('Notícia recebida')
            title_element = section.find('a', {'class': 'feed-post-link'})
            description_element = section.find(
                'div', {'class': 'feed-post-body-resumo'}
            )
            link_element = section.find('a', {'class': 'feed-post-link'})
            image_element = section.find(
                'img', {'class': 'bstn-fd-picture-image'}
            )

            if link_element:
                link_response = requests.get(
                    link_element['href'], timeout=10, headers=headers
                )
                link_content = BeautifulSoup(
                    link_response.content, 'html.parser'
                )

                full_text_content = link_content.find_all(
                    'div',
                    {'class': 'mc-column content-text active-extra-styles'},
                )
                media_content = link_content.find_all(
                    'div', {'class': 'mc-column content-media__container'}
                )

                full_text = ''
                media_links = []
                for text_section in full_text_content:
                    text = text_section.get_text(strip=True)
                    if text:
                        full_text += text + '\n\n'

                for media_section in media_content:
                    media_element = media_section.find('img')
                    if media_element and 'src' in media_element.attrs:
                        media_links.append(media_element['src'])
                        if 'src' in media_element.attrs:
                            image_url = media_element['src']
                        else:
                            image_url = None

                        full_text += f'<img src="{image_url}">\n\n'

                autor_element = link_content.find(
                    'p', {'class': 'content-publication-data__from'}
                )

                if (
                    title_element
                    and link_element
                    and description_element
                    and image_element
                ):
                    title = title_element.text.strip()
                    link = link_element['href']
                    description = description_element.text.strip()

                    if autor_element:
                        autor = autor_element.text
                    else:
                        autor = None

                    news_list.append(
                        {
                            'title': title,
                            'description': description,
                            'link': link,
                            'image': image_url
                            if 'image_url' in locals()
                            else None,
                            'autor': autor,
                            'full_text': full_text,
                            'media_links': media_links,
                        }
                    )
                    if len(news_list) >= limit:
                        break

        logger.info(f'{len(news_list)} notícias obtidas.')
        return news_list
    except Exception as e:
        logger.exception(f'Erro ao obter notícias: {str(e)}')
        return []


def upload_telegraph_image(image_url, attempt=0):
    logger.info('Fazendo upload da imagem no Telegraph...')
    if attempt == 3:
        return None

    telegraph_api = telegraph.Telegraph(TELEGRAPH)

    try:
        file = requests.get(image_url)
        if file.status_code != 200:
            logger.warning(f'Erro ao baixar imagem do link: {image_url}')
            return None

        inmemoryfile = io.BytesIO(file.content)
        path = telegraph_api.upload_file(inmemoryfile)
        return f'https://telegra.ph{path[0]["src"]}' if path else None

    except Exception as e:
        logger.exception(
            f'Erro ao fazer upload da imagem no Telegraph: {str(e)}'
        )
        return None


def create_telegraph_post(
    title, description, link, image_url, autor, full_text
):
    logger.info('Criando post no Telegraph...')
    try:
        telegraph_api = telegraph.Telegraph(TELEGRAPH)

        paragraphs = [
            f'<p>{paragraph}</p>' for paragraph in full_text.split('\n\n')
        ]
        formatted_text = ''.join(paragraphs)

        response = telegraph_api.create_page(
            f'{title}',
            html_content=(
                f'<img src="{image_url}"><br><br>'
                + f'<h4>{description}</h4><br><br>'
                + f'<p>{formatted_text}</p><br><br>'
                + f'<a href="{link}">Leia a matéria original</a>'
            ),
            author_name=f'{autor}',
        )
        return response['url'], title, link

    except Exception as e:
        logger.exception(f'Erro ao criar post no Telegraph: {str(e)}')
        return None, None, None


def create_telegraph_posts():
    logger.info('Criando posts no Telegraph...')
    news = get_news()
    telegraph_links = []

    for n in news:
        title = n['title']
        description = n['description']
        link = n['link']
        image_url = n['image']
        autor = n['autor']
        full_text = n['full_text']

        telegraph_link = create_telegraph_post(
            title, description, link, image_url, autor, full_text
        )
        if telegraph_link[0]:
            telegraph_links.append(telegraph_link)

    logger.info(f'{len(telegraph_links)} posts criados no Telegraph.')
    return telegraph_links


def total_news():
    try:
        all_news = db.get_all_news()
        total_count = len(list(all_news))
        bot.send_message(
            GROUP_LOG,
            f'TOTAL de Notícia enviada hoje: <code>{total_count}</code> Notícias',
        )
    except Exception as e:
        logger.exception(f'Error sending total news count: {str(e)}')


def delete_news():
    try:
        logger.info('Deletando todas as noticias do bnaco de dados...')
        db.remove_all_news()
    except Exception as e:
        logger.exception(
            f'Erro ao deletar as notícias do banco de dados: {str(e)}'
        )


def send_table_message():
    try:
        response = requests.get(
            'https://www.cnnbrasil.com.br/esportes/futebol/tabela-brasileirao-serie-a/'
        )
        content = response.content
        site = BeautifulSoup(content, 'html.parser')

        tabela = site.find('tbody', class_='table__body')

        linhas = tabela.find_all('tr', class_='body__row')

        message = '<b>Tabela do Brasileirão ⚽️🇧🇷</b>\n\n'
        for linha in linhas:
            classificacao = linha.find('span').text.strip()
            nome_time = linha.find('span', class_='hide__s').text.strip()

            dados_time = linha.find_all('td')
            pontos = dados_time[2].text.strip()
            jogos = dados_time[3].text.strip()
            vitorias = dados_time[4].text.strip()
            empates = dados_time[5].text.strip()
            derrotas = dados_time[6].text.strip()
            saldo_gols = dados_time[7].text.strip()

            table_row = (
                f'🏆 {classificacao} - <b>{nome_time}</b>\n'
                f'Pontos: {pontos} pts\n'
                f'Jogos: {jogos}\n'
                f'V: {vitorias} E: {empates} D: {derrotas}\n'
                f'Saldo de Gols: {saldo_gols}\n'
                f"{'━━━━━━━━━━━━━━━━━━'}\n\n"
            )
            message += table_row

        bot.send_message(CHANNEL, message, parse_mode='HTML')
        logger.info('Mensagem da tabela enviada com sucesso para o Telegram.')

    except Exception as e:
        logger.error(
            f'Erro ao enviar a mensagem da tabela para o Telegram: {str(e)}'
        )


def enviar_mensagem():
    url = 'https://www.placardefutebol.com.br/jogos-de-hoje'

    response = requests.get(url)

    jogos_campeonato_brasileiro = []

    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')

        containers = soup.find_all('div', class_='container content')

        for container in containers:
            links_jogos = container.find_all('a', href=True)
            for link_jogo in links_jogos:
                link = link_jogo['href']
                if '/brasileirao-serie-a/' in link:
                    status = link_jogo.find(
                        'span', class_='status-name'
                    ).text.strip()

                    team_home = link_jogo.find_all('h5', class_='team_link')[
                        0
                    ].text.strip()
                    team_away = link_jogo.find_all('h5', class_='team_link')[
                        1
                    ].text.strip()

                    if 'Encerrado' in status:
                        score_home = container.find_all(
                            'div', class_='match-score'
                        )[0].text.strip()
                        score_away = container.find_all(
                            'div', class_='match-score'
                        )[1].text.strip()
                        jogo = {
                            'Time da Casa': team_home,
                            'Placar Casa': score_home,
                            'Placar Visitante': score_away,
                            'Time Visitante': team_away,
                            'Status': status,
                        }
                    else:
                        jogo = {
                            'Time da Casa': team_home,
                            'Time Visitante': team_away,
                            'Status': status,
                        }

                    jogos_campeonato_brasileiro.append(jogo)

        mensagem = '<b>Jogos do Campeonato Brasileiro da Série A:</b>\n\n'
        for jogo in jogos_campeonato_brasileiro:
            if 'Placar Casa' in jogo:
                mensagem += f"{jogo['Time da Casa']} {jogo['Placar Casa']} - {jogo['Placar Visitante']} {jogo['Time Visitante']} ({jogo['Status']})\n"
            else:
                mensagem += f"{jogo['Time da Casa']} x {jogo['Time Visitante']} ({jogo['Status']})\n"

        bot.send_message(CHANNEL, mensagem)


def check_news_and_send():
    url = 'https://www.lance.com.br/mais-noticias.html'

    response = requests.get(url)

    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')

        cards = soup.find_all('div', class_='styles_card__XBZhk')

        if len(cards) > 0:
            for card in cards:
                title = card.find('h3').text.strip()

                link = card.find('a')['href']

                if db.search_title(title):
                    logger.info(f"A notícia '{title}' já foi postada.")
                else:
                    current_datetime = datetime.now() - timedelta(hours=3)
                    date = current_datetime.strftime('%d/%m/%Y - %H:%M:%S')
                    db.add_news(title, date)

                    # URL da imagem
                    image = card.find('img')['src']

                    button_text = (
                        f'https://www.lance.com.br{link}'  # Texto do botão
                    )
                    markup = types.InlineKeyboardMarkup()
                    btn_news = types.InlineKeyboardButton(
                        text='Ver notícia completa', url=button_text
                    )
                    markup.add(btn_news)

                    bot.send_photo(
                        CHANNEL,
                        photo=image,
                        caption=f'<b>{title}</b>\n\n<code>{date}</code>',
                        reply_markup=markup,
                    )
                    sleep(100)
        else:
            logger.info('Não foram encontradas notícias.')
    else:
        logger.info('Falha ao obter a página')


def send_news_g1():
    try:
        logger.info('Iniciando verificação e envio de notícias...')
        created_links = create_telegraph_posts()

        for telegraph_link, title, original_link in created_links:
            news_name = db.search_title(title)

            if news_name:
                logger.info('A notícia já foi postada.')
            else:
                logger.info('Adicionando notícia ao banco de dados...')
                current_datetime = datetime.now() - timedelta(hours=3)
                date = current_datetime.strftime('%d/%m/%Y - %H:%M:%S')
                db.add_news(title, date)

                logger.info('Enviando notícia...')
                bot.send_message(
                    CHANNEL,
                    f'<a href="{telegraph_link}">󠀠</a><b>{title}</b>\n\n'
                    f'🗞 <a href="{original_link}">G1 SPORTS</a>',
                    parse_mode='HTML',
                )
                sleep(300)
    except Exception as e:
        logger.exception(
            f'Erro durante verificação e envio de notícias: {str(e)}'
        )


def scrape_website(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            articles = soup.find_all(
                'div', class_='styles_card__XBZhk'
            )  # Altere essa classe de acordo com a estrutura do site

            for article in articles:
                title = article.find('h3').text.strip()
                image_url = article.find('img')['src']
                date = article.find(
                    'div', class_='styles_date__lZuoR'
                ).text.strip()

                author_elem = article.find(
                    'span', style='color: var(--green-lance);'
                )
                author = (
                    author_elem.text.strip()
                    if author_elem
                    else 'Autor não encontrado'
                )

                link_elem = article.find('a')
                link = (
                     link_elem['href']
                    if link_elem
                    else 'Link não encontrado'
                )

                send_to_bot(title, image_url, date, author, link)

    except requests.RequestException as e:
        logger.info(f'Request Exception: {e}')


def send_to_bot(title, image_url, date, author, link):
    try:
        if db.search_title(title):
            logger.info(f"A notícia '{title}' já foi postada.")
        else:
            current_datetime = datetime.now() - timedelta(hours=3)
            date = current_datetime.strftime('%d/%m/%Y - %H:%M:%S')
            db.add_news(title, date)

        button_text = f'https://www.lance.com.br{link}'  # Texto do botão
        markup = types.InlineKeyboardMarkup()
        btn_news = types.InlineKeyboardButton(
            text='Ver notícia completa', url=button_text
        )
        markup.add(btn_news)

        bot.send_photo(
            CHANNEL,
            photo=image_url,
            caption=f'<b>{title}</b>\n\n<code>{date}</code> - Feito por: {author}',
            reply_markup=markup,
        )
        sleep(100)
    except Exception as e:
        logger.info(f'Request Exception: {e}')


scrape_website('https://www.lance.com.br/futebol-nacional/mais-noticias.html')


def artilheiro_py():
    try:

        url = 'https://www.lance.com.br/tabela/brasileirao'

        response = requests.get(url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            artilheiros = soup.find_all(class_='styles_infoItem__oVN6c')[:10]

            for artilheiro in artilheiros:
                posicao = artilheiro.find(
                    class_='styles_infoPos__hzOKU'
                ).text.strip()
                nome_time = artilheiro.find(title=True)['title']
                nome_jogador = artilheiro.find(
                    class_='styles_playerName__iZPeZ'
                ).text.strip()
                posicao_jogador = artilheiro.find(
                    class_='styles_playerPosition__T9BX1'
                ).text.strip()
                jogos = artilheiro.find_all('span')[0].text.strip()
                media = artilheiro.find_all('span')[1].text.strip()
                gols = artilheiro.find('p').text.strip()

                send_artilheiro(
                    posicao,
                    nome_time,
                    nome_jogador,
                    posicao_jogador,
                    jogos,
                    media,
                    gols,
                )
        else:
            logger.info('Falha ao obter a página')
    except requests.RequestException as e:
        logger.info(f'Request Exception: {e}')


def send_artilheiro(
    posicao, nome_time, nome_jogador, posicao_jogador, jogos, media, gols
):
    try:
        message = '<b>Artilheiros do Brasileirão</b>\n\n'
        message += f'<b>Posição:</b> {posicao}\n'
        message += f'<b>Time:</b> {nome_time}\n'
        message += f'<b>Jogador:</b> {nome_jogador}\n'
        message += f'<b>Posição:</b> {posicao_jogador}\n'
        message += f'<b>Jogos:</b> {jogos}\n'
        message += f'<b>Média:</b> {media}\n'
        message += f'<b>Gols:</b> {gols}\n'
        message += '-' * 30 + '\n'

        bot.send_message(CHANNEL, message)
        sleep(100)
    except Exception as e:
        logger.info(f'Request Exception: {e}')


import requests
from bs4 import BeautifulSoup


def assitencia():
    try:
        url = 'https://www.lance.com.br/tabela/brasileirao'
        response = requests.get(url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            info_items = soup.find_all('div', class_='styles_infoItem__oVN6c')[
                :10
            ]

            for item in info_items:
                ranking = item.find(
                    'div', class_='styles_infoPos__hzOKU'
                ).text.strip()
                team_name = item.find('img')['title']
                player_name = item.find(
                    'span', class_='styles_playerName__iZPeZ'
                ).text
                position = item.find(
                    'span', class_='styles_playerPosition__T9BX1'
                ).text
                games = item.find_all('span')[0].text
                average = item.find_all('span')[1].text
                goals = item.find('p').text

                send_assitencia(
                    ranking,
                    team_name,
                    player_name,
                    position,
                    games,
                    average,
                    goals,
                )

        else:
            logger.info('Failed to retrieve the page.')
    except requests.RequestException as e:
        logger.info(f'Request Exception: {e}')


def send_assitencia(
    ranking, team_name, player_name, position, games, average, goals
):
    try:
        message = '<b>Assistências do Brasileirão</b>\n\n'
        message += f'<b>Posição:</b> {ranking}\n'
        message += f'<b>Time:</b> {team_name}\n'
        message += f'<b>Jogador:</b> {player_name}\n'
        message += f'<b>Posição:</b> {position}\n'
        message += f'<b>Jogos:</b> {games}\n'
        message += f'<b>Média:</b> {average}\n'
        message += f'<b>Assistências:</b> {goals}\n'
        message += '-' * 30 + '\n'

        bot.send_message(CHANNEL, message)
        sleep(100)
    except Exception as e:
        logger.info(f'Request Exception: {e}')


def ultimos_jogos():
    try:
        url = (
            'https://www.lance.com.br/resenha-de-apostas/mais-noticias?page=1'
        )
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')

        all_news = soup.find_all('a', class_='')

        brasileirao_titles = []
        brasileirao_images = []
        brasileirao_dates = []
        brasileirao_links = []

        for news in all_news:
            title = news.find('p', class_='text-more-news-title-desk-lg')
            image = news.find('img', class_='rounded-normal')
            date = news.find('p', class_='text-more-news-date-desk-lg')
            link = 'https://www.lance.com.br' + news['href']

            if title and title.text.startswith('Brasileirão'):
                title_text = brasileirao_titles.append(title.text)
                image_url = brasileirao_images.append(image['src'])
                date_text = brasileirao_dates.append(date.text)
                link_text = brasileirao_links.append(link)

            send_photo_lance(title_text, image_url, date_text, link_text)

    except requests.RequestException as e:
        logger.info(f'Request Exception: {e}')


def send_photo_lance(title_text, image_url, date_text, link_text):
    try:
        if db.search_title(title_text):
            logger.info(f"A notícia '{title_text}' já foi postada.")
        else:
            current_datetime = datetime.now() - timedelta(hours=3)
            date = current_datetime.strftime('%d/%m/%Y - %H:%M:%S')
            db.add_news(title_text, date)

        button_text = f'https://www.lance.com.br{link_text}'  # Texto do botão
        markup = types.InlineKeyboardMarkup()
        btn_news = types.InlineKeyboardButton(
            text='Ver notícia completa', url=button_text
        )
        markup.add(btn_news)

        bot.send_photo(
            CHANNEL,
            photo=image_url,
            caption=f'<b>{title_text}</b>\n\n<code>{date_text}</code>',
            reply_markup=markup,
        )
        sleep(100)
    except Exception as e:
        logger.info(f'Request Exception: {e}')


def fora_do_campo():
    try:
        url = 'https://www.lance.com.br/fora-de-campo/mais-noticias.html'

        response = requests.get(url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

            news_list = soup.find('ul', class_='styles_list__7maJJ')

            if news_list:
                for news_item in news_list.find_all('li'):
                    title = news_item.find('h3').text.strip()

                    image_url = (
                        'https://www.lance.com.br'
                        + news_item.find('img')['src']
                    )

                    datetime = news_item.find(
                        'div', class_='styles_date__lZuoR'
                    ).text.strip()

                    link = news_item.find('a')['href']

                    author = news_item.find(
                        'span', style='color:var(--green-lance)'
                    )
                    author_name = (
                        author.text if author else 'Autor não disponível'
                    )

                    send_text_fora_do_campo(
                        title, image_url, datetime, author_name, link
                    )

            else:
                logger.info('Lista de notícias não encontrada.')
        else:
            logger.info('Falha ao obter a página.')
    except requests.RequestException as e:
        logger.info(f'Request Exception: {e}')


def send_text_fora_do_campo(title, image_url, datetime, author_name, link):
    try:
        if db.search_title(title):
            logger.info(f"A notícia '{title}' já foi postada.")
        else:
            current_datetime = datetime.now() - timedelta(hours=3)
            date = current_datetime.strftime('%d/%m/%Y - %H:%M:%S')
            db.add_news(title, date)

        button_text = f'https://www.lance.com.br{link}'
        markup = types.InlineKeyboardMarkup()
        btn_news = types.InlineKeyboardButton(
            text='Ver notícia completa', url=button_text
        )
        markup.add(btn_news)

        bot.send_photo(
            CHANNEL,
            photo=image_url,
            caption=f'<b>{title}</b>\n\n<code>{datetime}</code> - Feito por {author_name}',
            reply_markup=markup,
        )
        sleep(100)
    except Exception as e:
        logger.info(f'Request Exception: {e}')


def libertadores():
    try:
        url = 'https://www.lance.com.br/libertadores/mais-noticias.html'
        response = requests.get(url)

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')

            posts = soup.find_all('div', class_='styles_card__XBZhk')

            for post in posts:
                title = post.find('h3').text.strip()
                image_url = post.find('img')['src']
                date_time = post.find(
                    'div', class_='styles_date__lZuoR'
                ).text.strip()
                author_tag = post.find(
                    'span', style='color:var(--green-lance)'
                )
                if author_tag:
                    author = author_tag.text.strip()
                else:
                    author = 'Author Not Found'
                post_url = 'https://www.lance.com.br' + post.find('a')['href']

                send_libertadores_text(
                    title, image_url, date_time, author, post_url
                )
        else:
            logger.info('Failed to retrieve the webpage')
    except requests.RequestException as e:
        logger.info(f'Request Exception: {e}')


def send_libertadores_text(title, image_url, date_time, author, post_url):
    try:
        if db.search_title(title):
            logger.info(f"A notícia '{title}' já foi postada.")
        else:
            current_datetime = datetime.now() - timedelta(hours=3)
            date = current_datetime.strftime('%d/%m/%Y - %H:%M:%S')
            db.add_news(title, date)

        button_text = f'https://www.lance.com.br{post_url}'  # Texto do botão
        markup = types.InlineKeyboardMarkup()
        btn_news = types.InlineKeyboardButton(
            text='Ver notícia completa', url=button_text
        )
        markup.add(btn_news)

        bot.send_photo(
            CHANNEL,
            photo=image_url,
            caption=f'<b>{title}</b>\n\n<code>{date_time}</code> - Feito por: {author}',
            reply_markup=markup,
        )
        sleep(100)
    except Exception as e:
        logger.info(f'Request Exception: {e}')


def check_match_status():
    url = 'https://www.placardefutebol.com.br/brasileirao-serie-a'
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    matches = soup.find_all('h3', class_='match-list_league-name')
    for match in matches:
        if match.text.strip() == 'Campeonato Brasileiro':
            match_info = match.find_next('a')
            match_time = match_info.find(
                'span', class_='status-name'
            ).text.strip()
            match_teams = match_info.find_all('h5', class_='team_link')
            home_team = match_teams[0].text.strip()
            away_team = match_teams[1].text.strip()

            if 'MIN' in match_time:
                send_message_to_channel(
                    f'A partida entre {home_team} e {away_team} começou!'
                )
            else:
                logger.info(
                    f'The match between {home_team} and {away_team} has not started yet.'
                )


def send_message_to_channel(message):
    try:
        bot.send_message(CHANNEL, text=message)
        logger.info(f'Message sent to the channel: {message}')
    except Exception as e:
        logger.info(f'Failed to send message to channel: {e}')


def status_gol():
    url = 'https://www.placardefutebol.com.br/'
    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html.parser')
    matches = soup.find_all('div', {'class': 'match-card-events'})

    for match in matches:
        try:
            gols = match.find_all('i', {'class': 'fa fa-futbol-o'})
            if gols:
                teams = match.find_all('div', {'class': 'team-name'})
                team_names = [team.text.strip() for team in teams]

                scores = match.find('div', {'class': 'match-score'})
                score_text = scores.text.strip().replace('\n', ' x ')

                goal_team = (
                    gols[0]
                    .find_previous('div', {'class': 'team-name'})
                    .text.strip()
                )

                message = f'goooooooooooooollll!!\nGolaço do {goal_team}\nPartida está:\n{team_names[0]} {score_text} {team_names[1]}'

                send_message_to_channel(message)
        except Exception as e:
            logger.info(f'Error: {e}')


def schedule_tasks():
    schedule.every().minute.do(check_match_status)
    schedule.every().minute.do(status_gol)
    schedule.every(15).minutes.do(send_news_g1)
    schedule.every(15).minutes.do(check_news_and_send)
    schedule.every(15).minutes.do(scrape_website)
    schedule.every(15).minutes.do(libertadores)
    schedule.every(15).minutes.do(fora_do_campo)
    schedule.every(15).minutes.do(ultimos_jogos)
    schedule.every(6).hours.do(enviar_mensagem)
    schedule.every(6).hours.do(send_table_message)
    schedule.every().day.at('08:20').do(enviar_mensagem)
    schedule.every().day.at('15:20').do(enviar_mensagem)
    schedule.every().day.at('18:20').do(enviar_mensagem)
    schedule.every().day.at('20:20').do(enviar_mensagem)
    schedule.every().day.at('10:15').do(send_table_message)
    schedule.every().day.at('15:15').do(assitencia)
    schedule.every().day.at('16:15').do(send_table_message)
    schedule.every().day.at('17:15').do(artilheiro_py)
    schedule.every().day.at('20:10').do(assitencia)
    schedule.every().day.at('21:15').do(send_table_message)
    schedule.every().day.at('22:10').do(artilheiro_py)
    schedule.every().day.at('00:00').do(delete_news)
    schedule.every().day.at('23:58').do(total_news)


def main():
    try:
        logger.info('BOT INICIANDO...')
        schedule_tasks()

        while True:
            schedule.run_pending()
            sleep(60)  
    except KeyboardInterrupt:
        logger.info(
            'Encerrando o bot devido ao comando de interrupção (Ctrl+C)'
        )
    except Exception as e:
        logger.exception(f'Erro não tratado: {str(e)}')


if __name__ == '__main__':
    main()
