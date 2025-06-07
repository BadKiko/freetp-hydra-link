import requests
from bs4 import BeautifulSoup
import json
import logging
from datetime import datetime
import re
import sys
import os
import time
import hashlib
import base64
import urllib.parse
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import bencodepy

# Настройка логирования - повышаем уровень для отладки
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# Создаем одну сессию для всех запросов
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
    'Referer': 'https://freetp.org/'
})

def get_magnet_link(torrent_data):
    """Generate a magnet link from torrent data"""
    try:
        if b'info' not in torrent_data:
            logging.error("Нет ключа 'info' в данных торрента")
            return None
        
        # Generate info hash
        info_data = bencodepy.encode(torrent_data[b'info'])
        info_hash = hashlib.sha1(info_data).digest()
        info_hash_encoded = base64.b32encode(info_hash).decode().rstrip('=')  # Удаляем padding '='
        
        # Get name
        name = ""
        if b'name' in torrent_data[b'info']:
            name = torrent_data[b'info'][b'name'].decode('utf-8', errors='replace')
        
        # Get trackers
        trackers = []
        if b'announce' in torrent_data:
            trackers.append(torrent_data[b'announce'].decode('utf-8', errors='replace'))
        if b'announce-list' in torrent_data:
            for announce_list in torrent_data[b'announce-list']:
                for announce in announce_list:
                    if isinstance(announce, bytes):
                        tracker = announce.decode('utf-8', errors='replace')
                        if tracker not in trackers:
                            trackers.append(tracker)
        
        # Build magnet link
        magnet = f"magnet:?xt=urn:btih:{info_hash_encoded}"
        if name:
            magnet += f"&dn={urllib.parse.quote(name)}"
        for tracker in trackers:
            magnet += f"&tr={urllib.parse.quote(tracker)}"
        
        logging.info(f"Создана магнет-ссылка: {magnet[:60]}...")
        return magnet
    except Exception as e:
        logging.error(f"Ошибка при создании магнет-ссылки: {e}")
        return None

def fetch_games(url, retries=3, timeout=10):
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=timeout)
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
    logging.info(f"Найдено {len(game_divs)} игр на странице {url}")
    
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
                logging.info(f"Обработка игры: {title} ({game_link})")
                download_link, file_size, upload_date, magnet_link = fetch_download_link_and_size(game_link)
                
                # Добавляем игру только если есть magnet-ссылка
                if magnet_link:
                    games.append({
                        'title': title,
                        'uris': [magnet_link],
                        'uploadDate': upload_date,
                        'fileSize': file_size
                    })
                    logging.info(f"[GAME] Обработана игра: {title}")
                else:
                    logging.warning(f"[GAME] Не удалось получить магнет-ссылку для {title}")

    logging.info(f"Всего обработано игр: {len(games)}")
    return games

def fetch_download_link_and_size(game_url, retries=3, timeout=10):
    for attempt in range(retries):
        try:
            response = session.get(game_url, timeout=timeout)
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

    logging.info(f"[DOWNLOAD] Скачивание торрент-файла: {download_link}")
    
    # Добавляем задержку перед загрузкой торрент-файла
    time.sleep(1)
    
    # Скачивание .torrent файла
    try:
        torrent_response = session.get(download_link, headers={
            'Referer': game_url,
            'Accept': 'application/x-bittorrent,*/*'
        })
        
        # Проверка содержимого ответа
        content_type = torrent_response.headers.get('Content-Type', '')
        if 'html' in content_type.lower() or torrent_response.content.startswith(b'<!DOCTYPE') or torrent_response.content.startswith(b'<html'):
            logging.error(f"[DOWNLOAD] Получен HTML вместо торрент-файла. Содержимое: {torrent_response.content[:200]}...")
            
            # Попробуем посмотреть, есть ли в HTML прямая ссылка на торрент
            soup = BeautifulSoup(torrent_response.content, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                if a_tag['href'].endswith('.torrent'):
                    new_link = a_tag['href']
                    if new_link.startswith('/'):
                        new_link = f"https://freetp.org{new_link}"
                    logging.info(f"[DOWNLOAD] Найдена альтернативная ссылка на торрент: {new_link}")
                    
                    time.sleep(1)
                    torrent_response = session.get(new_link, headers={
                        'Referer': download_link,
                        'Accept': 'application/x-bittorrent,*/*'
                    })
                    break
            else:
                return None, None, None, None
            
        torrent_file_path = 'temp.torrent'
        with open(torrent_file_path, 'wb') as f:
            f.write(torrent_response.content)

        if os.path.getsize(torrent_file_path) == 0:
            logging.error(f"[TORRENT] Файл {torrent_file_path} пуст.")
            return None, None, None, None
        
        # Проверяем, что файл действительно торрент, а не HTML
        with open(torrent_file_path, 'rb') as f:
            content_start = f.read(10)
            if content_start.startswith(b'<!DOCTYPE') or content_start.startswith(b'<html'):
                logging.error(f"[TORRENT] Файл {torrent_file_path} содержит HTML, а не торрент данные.")
                return None, None, None, None
                
    except Exception as e:
        logging.error(f"[DOWNLOAD] Ошибка при скачивании торрент-файла: {e}")
        return None, None, None, None
    
    # Извлечение информации из торрент-файла с использованием bencodepy
    try:
        # Используем bencodepy для чтения метаданных торрент-файла
        with open(torrent_file_path, 'rb') as f:
            torrent_data = bencodepy.decode(f.read())
        
        # Создаем magnet-ссылку
        magnet_link = get_magnet_link(torrent_data)
        if not magnet_link:
            logging.error("[MAGNET] Не удалось создать магнет-ссылку")
            return None, None, None, None
        
        # Извлечение размера игры
        file_size = 0
        if b'info' in torrent_data and b'length' in torrent_data[b'info']:
            file_size = torrent_data[b'info'][b'length']
        elif b'info' in torrent_data and b'files' in torrent_data[b'info']:
            # Если торрент содержит несколько файлов
            file_size = sum(file[b'length'] for file in torrent_data[b'info'][b'files'])
        
        if file_size > 1024 * 1024 * 1024:
            file_size = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
        elif file_size > 1024 * 1024:
            file_size = f"{file_size / (1024 * 1024):.2f} MB"
        else:
            file_size = f"{file_size / 1024:.2f} KB"
        
        # Извлечение даты загрузки
        upload_date = datetime.now().strftime('%d-%m-%Y, %H:%M')
        if b'creation date' in torrent_data:
            upload_date = datetime.fromtimestamp(torrent_data[b'creation date']).strftime('%d-%m-%Y, %H:%M')
        
        return download_link, file_size, upload_date, magnet_link
        
    except Exception as e:
        logging.error(f"[TORRENT] Ошибка при обработке файла {torrent_file_path}: {e}")
        return None, None, None, None

def save_to_json(games, filename='games.json'):
    data = {
        "name": "FreeTP",
        "downloads": games
    }
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.info(f"JSON файл успешно сохранен: {filename} ({len(games)} игр)")
        return True
    except Exception as e:
        logging.error(f"Ошибка при сохранении JSON: {e}")
        return False

def main():
    base_url = 'https://freetp.org/page/'
    all_games = []
    
    # Начальная страница
    current_page = 1
    not_found_count = 0
    max_pages = 400  # Примерно столько страниц на сайте
    
    # Создаем прогресс-бар
    pbar = tqdm(total=max_pages, desc="Обработка страниц", unit="страница")
    
    # Последовательная обработка страниц с прогресс-баром
    while True:
        try:
            logging.info(f"Обрабатываю страницу {current_page}")
            
            # Попытка получить игры с текущей страницы
            response = session.get(f'{base_url}{current_page}/', timeout=10)
            
            # Если страница не найдена (404)
            if response.status_code == 404:
                logging.warning(f"Страница {current_page} не найдена (404)")
                not_found_count += 1
                
                # Если уже 3 страницы подряд отдали 404, заканчиваем
                if not_found_count >= 3:
                    logging.info(f"Три страницы подряд отдали 404, завершаем парсинг")
                    break
                
                # Иначе переходим к следующей странице
                current_page += 1
                pbar.update(1)
                continue
            
            # Если страница успешно загружена, сбрасываем счетчик 404
            not_found_count = 0
            
            # Получаем игры с текущей страницы
            games = fetch_games(f'{base_url}{current_page}/')
            
            if games:
                all_games.extend(games)
                logging.info(f"[PAGE] Обработана страница: {current_page} (Добавлено {len(games)} игр)")
            else:
                logging.warning(f"[PAGE] Страница {current_page} не содержит игр")
            
            # Обновляем прогресс-бар и переходим к следующей странице
            pbar.update(1)
            current_page += 1
            
            # Сохраняем промежуточные результаты каждые 10 страниц
            if current_page % 10 == 0 and all_games:
                save_to_json(all_games, f"games_temp_{current_page}.json")
                logging.info(f"Сохранен промежуточный результат: {len(all_games)} игр")
            
        except Exception as exc:
            logging.error(f"[PAGE] Страница {current_page} вызвала исключение: {exc}")
            pbar.update(1)
            current_page += 1
    
    # Закрываем прогресс-бар
    pbar.close()

    logging.info(f"Всего найдено игр: {len(all_games)}")
    
    if all_games:
        save_to_json(all_games)
    else:
        logging.error("Не удалось получить данные об играх.")

if __name__ == '__main__':
    main() 