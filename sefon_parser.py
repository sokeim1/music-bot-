"""
Парсер для sefon.pro - поиск и скачивание музыки
"""
import aiohttp
import re
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from urllib.parse import quote, urljoin


class SefonParser:
    """Класс для работы с sefon.pro"""
    
    BASE_URL = "https://sefon.pro"
    SEARCH_URL = f"{BASE_URL}/search/"
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search(self, query: str, limit: int = 5) -> List[Dict[str, str]]:
        """
        Поиск музыки по запросу
        
        Args:
            query: поисковый запрос
            limit: максимальное количество результатов
            
        Returns:
            Список словарей с информацией о треках:
            - title: название трека
            - artist: исполнитель
            - duration: длительность
            - track_url: ссылка на страницу трека
        """
        if not self.session:
            raise RuntimeError("Используйте 'async with SefonParser()' для создания сессии")
        
        # Формируем URL для поиска
        search_url = f"{self.SEARCH_URL}?q={quote(query)}"
        
        try:
            async with self.session.get(search_url) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                soup = BeautifulSoup(html, 'lxml')
                
                results = []
                seen_urls = set()
                
                # Ищем все ссылки на треки (/mp3/...)
                for link in soup.find_all('a', href=True):
                    href = link.get('href', '')
                    
                    # Ищем ссылки на треки вида /mp3/xxxxx-название/
                    if '/mp3/' in href and href not in seen_urls:
                        seen_urls.add(href)
                        
                        # Формируем полный URL
                        track_url = urljoin(self.BASE_URL, href)
                        
                        # Парсим название трека из URL
                        # Формат: /mp3/55112-eminem-lose-yourself/
                        track_slug = href.split('/mp3/')[-1].strip('/')
                        parts = track_slug.split('-', 1)
                        
                        if len(parts) < 2:
                            continue
                        
                        # Получаем текст ссылки (часто содержит исполнителя или название)
                        link_text = link.get_text(strip=True)
                        
                        # Пытаемся найти исполнителя и название
                        # Проверяем предыдущие элементы для поиска исполнителя
                        artist = "Неизвестный исполнитель"
                        title = link_text if link_text else parts[1].replace('-', ' ').title()
                        
                        # Ищем ближайшие ссылки на исполнителя (/artist/...)
                        parent = link.parent
                        if parent:
                            artist_links = parent.find_all('a', href=re.compile(r'/artist/'))
                            if artist_links:
                                artist = artist_links[0].get_text(strip=True)
                        
                        results.append({
                            'title': title,
                            'artist': artist,
                            'duration': 'N/A',
                            'track_url': track_url,
                            'full_name': f"{artist} - {title}"
                        })
                        
                        if len(results) >= limit:
                            break
                
                return results
                
        except Exception as e:
            print(f"Ошибка поиска: {e}")
            return []
    
    async def download_track(self, track_url: str) -> Optional[bytes]:
        """
        Скачивание трека по ссылке
        
        Args:
            track_url: ссылка на страницу трека
            
        Returns:
            Байты аудио файла или None в случае ошибки
        """
        if not self.session:
            raise RuntimeError("Используйте 'async with SefonParser()' для создания сессии")
        
        try:
            # Получаем страницу трека
            async with self.session.get(track_url) as response:
                if response.status != 200:
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'lxml')
                
                # Ищем элемент <source> внутри <audio> тега или data-атрибуты
                mp3_link = None
                
                # Вариант 1: ищем audio source
                audio_tag = soup.find('audio')
                if audio_tag:
                    source = audio_tag.find('source')
                    if source and source.get('src'):
                        mp3_link = source['src']
                
                # Вариант 2: ищем data-url атрибут в любом элементе
                if not mp3_link:
                    for elem in soup.find_all(attrs={'data-url': True}):
                        mp3_link = elem['data-url']
                        if mp3_link:
                            break
                
                # Вариант 3: ищем прямую ссылку на .mp3 файл
                if not mp3_link:
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if '.mp3' in href and 'http' in href:
                            mp3_link = href
                            break
                
                # Вариант 4: пробуем построить прямую ссылку из URL трека
                # Формат: /mp3/55112-eminem-lose-yourself/ -> /mp3/download/55112/
                if not mp3_link:
                    track_id = track_url.split('/mp3/')[-1].split('-')[0]
                    if track_id.isdigit():
                        mp3_link = f"{self.BASE_URL}/mp3/download/{track_id}/"
                
                if not mp3_link:
                    print(f"Не удалось найти ссылку на MP3 для {track_url}")
                    return None
                
                # Если ссылка относительная, делаем её абсолютной
                if not mp3_link.startswith('http'):
                    mp3_link = urljoin(self.BASE_URL, mp3_link)
                
                # Скачиваем MP3 файл
                async with self.session.get(mp3_link, allow_redirects=True) as mp3_response:
                    if mp3_response.status == 200:
                        content_type = mp3_response.headers.get('content-type', '')
                        # Проверяем, что это аудио файл
                        if 'audio' in content_type or 'octet-stream' in content_type:
                            return await mp3_response.read()
                    return None
                    
        except Exception as e:
            print(f"Ошибка скачивания: {e}")
            return None
