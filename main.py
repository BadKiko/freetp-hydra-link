import requests
from bs4 import BeautifulSoup
import json
import logging
from datetime import datetime
import re
from torrentool.api import Torrent
from concurrent.futures import ThreadPoolExecutor, as_completed

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def fetch_games(url):
    response = requests.get(url)
    if response.status_code != 200:
        logging.error(f"[PAGE] Ошибка при получении данных с сайта: {response.status_code}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    games = []

    # Парсинг игр на странице
    for game_div in soup.find_all('div', class_='base'):
        title_tag = game_div.find('div', class_='header-h1').find('h1')
        if title_tag:
            # Очистка заголовка от различных суффиксов
            title = title_tag.get_text(strip=True)
            suffixes_to_remove = [
                ' играть по сети и интернету Онлайн',
                ' / ЛАН',
                ' играть по сети и Интернету Онлайн',
                ' играть по сети интернету ЛАН',
                ' играть по сети интернету Онлайн'
            ]
            for suffix in suffixes_to_remove:
                title = title.replace(suffix, '')

            # Извлечение ссылки на страницу игры
            link_tag = game_div.find('div', class_='header-h1').find('a')
            game_link = link_tag['href'] if link_tag else None

            if game_link:
                download_link, file_size, upload_date, magnet_link = fetch_download_link_and_size(game_link)
                games.append({
                    'title': title,
                    'uris': [magnet_link] if magnet_link else [],
                    'uploadDate': upload_date,
                    'fileSize': file_size
                })
                logging.info(f"[GAME] Обработана игра: {title}")

    return games

def fetch_download_link_and_size(game_url):
    response = requests.get(game_url)
    if response.status_code != 200:
        logging.error(f"[GAME PAGE] Ошибка при получении данных с сайта: {response.status_code}")
        return None, None, None, None

    soup = BeautifulSoup(response.content, 'html.parser')

    # Извлечение ссылки на скачивание
    download_link = None

    for a_tag in soup.find_all('a', href=True, target="_blank"):
        if 'getfile' in a_tag['href']:
            download_link = 'https://freetp.org/engine/download.php?id=' + ''.join(filter(str.isdigit, a_tag['href'])) + '&area='
            break

    if not download_link:
        logging.warning(f"[DOWNLOAD] Ссылка на скачивание не найдена для {game_url}")
        return None, None, None, None

    # Проверка и добавление схемы к URL, если необходимо
    if download_link.startswith('//'):
        download_link = 'https:' + download_link
    elif download_link.startswith('/'):
        download_link = 'https://freetp.org' + download_link

    # Скачивание .torrent файла
    torrent_response = requests.get(download_link)
    torrent_file_path = 'temp.torrent'
    with open(torrent_file_path, 'wb') as f:
        f.write(torrent_response.content)

    # Извлечение magnet-ссылки
    torrent = Torrent.from_file(torrent_file_path)
    magnet_link = torrent.magnet_link

    # Извлечение размера игры
    file_size = torrent.total_size
    if file_size > 1024 * 1024 * 1024:
        file_size = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
    elif file_size > 1024 * 1024:
        file_size = f"{file_size / (1024 * 1024):.2f} MB"
    else:
        file_size = f"{file_size / 1024:.2f} KB"
    # Извлечение даты загрузки
    upload_date = torrent.creation_date.strftime('%d-%m-%Y, %H:%M')

    return download_link, file_size, upload_date, magnet_link

def save_to_json(games, filename='games.json'):
    data = {
        "name": "FreeTP",
        "downloads": games
    }
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def main():
    base_url = 'https://freetp.org/page/'
    all_games = []

    # Используем ThreadPoolExecutor для многопоточной обработки
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_games, f'{base_url}{page}/'): page for page in range(1, 51)}
        for future in as_completed(future_to_url):
            page = future_to_url[future]
            try:
                games = future.result()
                all_games.extend(games)
                logging.info(f"[PAGE] Обработана страница: {page}")
            except Exception as exc:
                logging.error(f"[PAGE] Страница {page} вызвала исключение: {exc}")

    if all_games:
        save_to_json(all_games)
        logging.info(f"[JSON] Данные об играх сохранены в games.json")
    else:
        logging.error("Не удалось получить данные об играх.")

if __name__ == '__main__':
    main() 