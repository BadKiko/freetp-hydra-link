import requests
from bs4 import BeautifulSoup
import json
import logging
from datetime import datetime
import re
import sys
import os
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import bencodepy

# Добавляем путь к локальной библиотеке torrentool
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'torrentool'))

from torrentool.api import Torrent

# Настройка логирования
logging.basicConfig(level=logging.CRITICAL, format='[%(levelname)s] %(message)s')

def fetch_games(url, retries=3, timeout=10):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                break
            else:
                logging.error(f"[PAGE] Ошибка при получении данных с сайта: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.error(f"[PAGE] Ошибка запроса: {e}")
        
        if attempt < retries - 1:
            logging.info(f"[PAGE] Повторная попытка {attempt + 1} для {url}")
            time.sleep(2)  # Задержка перед повторной попыткой
    else:
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    games = []

    # Парсинг игр на странице с прогресс-баром
    game_divs = soup.find_all('div', class_='base')
    for game_div in tqdm(game_divs, desc="Обработка игр", unit="игра"):
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

def fetch_download_link_and_size(game_url, retries=3, timeout=10):


    for attempt in range(retries):
        try:
            response = requests.get(game_url, timeout=timeout)
            if response.status_code == 200:
                break
            else:
                logging.error(f"[GAME PAGE] Ошибка при получении данных с сайта: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.error(f"[GAME PAGE] Ошибка запроса: {e}")
        
        if attempt < retries - 1:
            logging.info(f"[GAME PAGE] Повторная попытка {attempt + 1} для {game_url}")
            time.sleep(2)  # Задержка перед повторной попыткой
    else:
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

    if os.path.getsize(torrent_file_path) == 0:
        logging.error(f"[TORRENT] Файл {torrent_file_path} пуст.")
        return None, None, None, None
    # Извлечение magnet-ссылки
    try:
        torrent = Torrent.from_file(torrent_file_path)
    except Exception as e:
        logging.error(f"[TORRENT] Ошибка при обработке файла {torrent_file_path}: {e}")
        return None, None, None, None
    
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

    # Последовательная обработка страниц с прогресс-баром
    for page in tqdm(range(5, 10), desc="Обработка страниц", unit="страница"):
        try:
            games = fetch_games(f'{base_url}{page}/')
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