# The MIT License (MIT)
#
# Copyright (c) 2022-2024 Péter Tombor.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
import signal
from time import sleep
from typing import List

import pycron
from fire import Fire

from . import DiskManager, __version__
from .ItchGame import ItchGame
from .ItchUser import ItchUser
from .web import generate_web

import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# pylint: disable=missing-class-docstring
class ItchClaim:
    def __init__(self,
                version: bool = False,
                login: str = None,
                password: str = None,
                totp: str = None):
        """Automatically claim free games from itch.io"""
        if version:
            self.version()
        # Try loading username from environment variables if not provided as command line argument
        if login is None and os.getenv('ITCH_USERNAME') is not None:
            login = os.getenv('ITCH_USERNAME')
        if login is not None:
            self.login(login, password, totp)
            while self.user.username == None:
                sleep(1)
                self.login(login, password, totp)
            print(f'Logged in as {self.user.username}', flush=True)
        else:
            self.user = None

    def version(self):
        """Display the version of the script and exit"""
        print(__version__)
        exit(0)

    def refresh_sale_cache(self, games_dir: str = 'web/data/', sales: List[int] = None):
        """Refresh the cache about game sales
        Opens itch.io and downloads sales posted after the last saved one.

        Args:
            games_dir (str): Output directory
            sales: (List[int]): Only refresh the sales specified in this list"""
        resume = 1
        ItchGame.games_dir = games_dir
        os.makedirs(games_dir, exist_ok=True)

        if sales:
            print('--sales flag found - refreshing only select sale pages')
            for sale_id in sales:
                DiskManager.get_one_sale(sale_id)
            return

        try:
            with open(os.path.join(games_dir, 'resume_index.txt'), 'r', encoding='utf-8') as f:
                resume = int(f.read())
                print(f'Resuming sale downloads from {resume}')
        except FileNotFoundError:
            print('Resume index not found. Downloading sales from beginning')

        DiskManager.get_all_sales(resume)

        print('Updating games from sale lists, to catch updates of already known sales.', flush=True)

        for category in ['games', 'tools', 'game-assets', 'comics', 'books', 'physical-games',
                'soundtracks', 'game-mods', 'misc']:
            print(f'Collecting sales from {category} list', flush=True)
            DiskManager.get_all_sale_pages(category=category)

    def refresh_library(self):
        """Refresh the list of owned games of an account. This is used to skip claiming already
        owned games. Requires login."""
        if self.user is None:
            print('You must be logged in')
            return
        self.user.reload_owned_games()
        self.user.save_session()

    def claim(self, url: str = 'https://itchclaim.tmbpeter.com/api/active.json'):
        """Claim all unowned games. Requires login.
        Args:
            url (str): The URL to download the file from"""

        if self.user is None:
            print('You must be logged in')
            return
        if len(self.user.owned_games) == 0:
            print('User\'s library not found in cache. Downloading it now', flush=True)
            self.user.reload_owned_games()
            self.user.save_session()

        print(f'Downloading free games list from {url}', flush=True)
        games = DiskManager.download_from_remote_cache(url)

        print('Claiming games', flush=True)
        claimed_games = 0
        for game in games:
            for owned_url in [owned_game.url for owned_game in self.user.owned_games]:
                if owned_url == url:
                    continue

            if not self.user.owns_game(game):
                self.user.claim_game(game)
                self.user.save_session()
                claimed_games += 1
        if claimed_games == 0:
            print('No new games can be claimed.', flush=True)

    def schedule(self, cron: str, url: str = 'https://itchclaim.tmbpeter.com/api/active.json'):
        """Start an infinite process of the script that claims games at a given schedule.
        Args:
            cron (str): The cron schedule to claim games
                See crontab.guru for syntax
            url (str): The URL to download the file from"""
        print(f'Starting cron job with schedule {cron}')

        # Define the signal handler
        def signal_handler(signum, frame):
            print("Interrupt signal received. Exiting...")
            exit(0)

        # Register the signal handler
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Start the scheduler
        while True:
            if not pycron.is_now(cron):
                sleep(60)
                continue
            self.claim(url)
            sleep(60)
        

    def download_urls(self, game_url: int):
        """Get details about a game, including it's CDN download URLs.

        Args:
            game_url (int): The url of the requested game."""
        game: ItchGame = ItchGame.from_api(game_url)
        session = self.user.s if self.user is not None else None
        print(game.downloadable_files(session))

    def generate_web(self, web_dir: str = 'web'):
        """Generates files that can be served as a static website
        
        Args:
            web_dir (str): Output directory"""

        ItchGame.games_dir = os.path.join(web_dir, 'data')
        os.makedirs(os.path.join(web_dir, 'api'), exist_ok=True)
        os.makedirs(ItchGame.games_dir, exist_ok=True)

        games = DiskManager.load_all_games()
        generate_web(games, web_dir)

    def login(self,
                username: str = None,
                password: str = None,
                totp: str = None) -> ItchUser:
        """Load session from disk if exists, or use password otherwise.

        Args:
            username (str): The username or email address of the user
            password (str): The password of the user
            totp (str): The 2FA code of the user
                Either the 6 digit code, or the secret used to generate the code
        
        Returns:
            ItchUser: a logged in ItchUser instance
        """
        self.user = ItchUser(username)
        try:
            self.user.load_session()
            print(f'Session {username} loaded successfully', flush=True)
        except FileNotFoundError:
            # Try loading password from environment variables if not provided as command line argument
            if password is None:
                password = os.getenv('ITCH_PASSWORD')
            # Try loading TOTP from environment variables if not provided as command line argument
            if totp is None:
                totp = os.getenv('ITCH_TOTP')
            self.user.login(password, totp)



    def _find_game(self, games_list, url):
        for game in games_list:
            if game.url == url:
                return True
        return False



    def _substr(self, str: str, idx0, pat1: str, pat2: str):
        idx1 = str.find(pat1, idx0)
        if idx1 == -1:
            return None

        idx1 += len(pat1)
        idx2 = str.find(pat2, idx1)

        if idx2 == -1:
            return None

        return str[idx1:idx2]



    def _owns_game(self, url: str):
        for owned_url in [owned_game.url for owned_game in self.user.owned_games]:
            if owned_url == url:
                return True
        return False



    def _dump_log(self, filename: str, mylist):
        if len(mylist) == 0:
            return

        with open(filename, 'w') as myfile:
            for line in mylist:
                print(line, file=myfile)  # Python 3.x



    def _send_web(self, type: str, url: str, redirect = True, payload = None):
        timer = 10

        count = 0
        while True:
            sleep(1/1000)

            try:
                if type == 'get':
                    r = requests.get(url, data=payload, timeout=timer, allow_redirects=redirect)
                if type == 'post':
                    r = requests.post(url, data=payload, timeout=timer, allow_redirects=redirect)

                if type == 'user_get':
                    r = self.user.s.get(url, data=payload, timeout=timer, allow_redirects=redirect)
                if type == 'user_post':
                    r = self.user.s.post(url, data=payload, timeout=timer, allow_redirects=redirect)

                r.encoding = 'utf-8'

            except requests.RequestException as err:
                print(err, flush=True)
                # pass


            if r.status_code == 200:  # OK
                break
            if r.status_code == 404:  # Not found
                break
            if r.status_code == 301:  # Redirect
                break
            if r.status_code == 429:  # Too many requests
                sleep(10/1000)
                continue


            count += 1
            if count == 100:
                print('Too many attempts. Aborting\n\n', flush=True)
                print(r.status_code, flush=True)
                print(r.text, flush=True)
                exit(1)
        return r



    def _claim_game(self, game: ItchGame):
        try:
            r = self.s.post(game.url + '/download_url', json={'csrf_token': self.csrf_token})
            r.encoding = 'utf-8'
            resp = json.loads(r.text)
        except:
            print(f"ERROR: Failed to check {game.url}", flush=True)
            return
        if 'errors' in resp:
            if resp['errors'][0] in ('invalid game', 'invalid user'):
                if game.check_redirect_url():
                    self.claim_game(game)
                    return
            print(f"ERROR: Failed to claim {game.url}     {resp['errors'][0]}", flush=True)
            return


        download_url = json.loads(r.text)['url']
        r = self.s.get(download_url)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        claim_box = soup.find('div', class_='claim_to_download_box warning_box')
        if claim_box == None:
            print(f"{game.url} is not claimable", flush=True)
            return


        claim_url = claim_box.find('form')['action']
        r = self.s.post(claim_url,
                        data={'csrf_token': self.csrf_token},
                        headers={ 'Content-Type': 'application/x-www-form-urlencoded'}
                        )
        r.encoding = 'utf-8'
        if r.url == 'https://itch.io/':
            if self.owns_game_online(game):
                self.owned_games.append(game)
                print(f"{game.url} has already been claimed", flush=True)
                return
            print(f"ERROR: Unknown failure to claim {game.url}", flush=True)
        else:
            self.owned_games.append(game)
            print(f"Successfully claimed {game.url}", flush=True)


    def _claim_reward(self, game: ItchGame):
        self.valid_reward = False

        try:
            r = self._send_web('get', game.url + '/data.json')

            dat = json.loads(r.text)
            if 'rewards' not in dat:
                return

            for item in dat['rewards']:
                # print(item, flush=True)

                idx = 0
                while item['price'][idx].isdigit() == False:
                    idx += 1

                if item['price'][idx:] != '0.00':
                    continue


                print(game.url, flush=True)
                self.valid_reward = True

                if item['available'] != True:
                    continue


                r = self._send_web('user_post', game.url + '/download_url?csrf_token=' + self.user.csrf_token + '&reward_id=' + str(item['id']))

                download_url = json.loads(r.text)['url']
                r = self._send_web('user_get', download_url)

                soup = BeautifulSoup(r.text, 'html.parser')
                claim_box = soup.find('div', class_='claim_to_download_box warning_box')
                if claim_box == None:
                    raise Exception("No claim box") 

                claim_url = claim_box.find('form')['action']
                r = self._send_web('user_post', claim_url, True, {'csrf_token': self.user.csrf_token})
                if r.url == 'https://itch.io/':
                    raise Exception(r.text)

                self.user.owned_games.append(game)
                print(f"Successfully claimed {game.url}", flush=True)

        except Exception as err:
            print('[_claim_reward] Failure while claiming ' + game.url + ' = ' + str(err), flush=True)



    def scrape_sales(self, scrape_page = -1, scrape_limit = -1, scrape_step = 5000):
        """Claim all unowned games. Requires login.
        Args:
            url (str): The URL to download the file from"""

        if self.user is None:
            print('You must be logged in', flush=True)
            return

        if len(self.user.owned_games) == 0:
            print('User\'s library not found in cache. Downloading it now', flush=True)
            self.user.reload_owned_games()
            self.user.save_session()


        active_list = set()  # hashed, faster lookup
        future_list = set()
        owned_list = set()


        active_db = DiskManager.download_from_remote_cache('https://itchclaim.tmbpeter.com/api/active.json')
        future_db = DiskManager.download_from_remote_cache('https://itchclaim.tmbpeter.com/api/upcoming.json')

        for game in active_db:
            active_list.add(game.url)

        for game in future_db:
            future_list.add(game.url)

        for game_url in [owned_game.url for owned_game in self.user.owned_games]:
            owned_list.add(game_url)


        if scrape_limit == -1:
            r = self._send_web('get', 'http://itchclaim.tmbpeter.com/data/resume_index.txt')
            scrape_limit = int(r.text)

        if scrape_page == -1:
            r = self._send_web('get', 'https://raw.githubusercontent.com/li1ht2ay-3es/it1h-c2ai3/scrape-sales-ci/scrape.txt')
            scrape_page = int(r.text)


        miss_log = []  # not for searching
        future_log = []
        sales_log = []
        sales_list = []


        try:
            r = self._send_web('get', 'https://raw.githubusercontent.com/li1ht2ay-3es/it1h-c2ai3/zz-sales-' + str(scrape_page) + '/sales-url.txt')

            if r.status_code == 200:
                for sales_url in r.text.splitlines():
                    sales_list.append(sales_url)

        except Exception as err:
            print('Failure reading ' + 'sales-url.txt' + ' = ' + str(err), flush=True)


        print(f'Scraping {scrape_page} ...', flush=True)


        page_count = 0

        if scrape_page == 0:  # sale 0 = n/a
            page_count = 1
            scrape_page = 1


        while page_count < scrape_step and scrape_page < scrape_limit:
            try:
                if page_count < len(sales_list):
                    url = sales_list[page_count]

                else:
                    url = f"https://itch.io/s/{scrape_page}"
                    r = self._send_web('get', url, False)

                    if 'Location' in r.headers:
                        url = r.headers['Location']

                    sales_list.append(url)

                page_count += 1
                scrape_page += 1


                r = self._send_web('get', url)

                if 'This sale ended' in r.text:
                    continue

                if '100%</strong> off' not in r.text:
                    continue

                sale_url = url
                print(sale_url, flush=True)


                future_sale = False
                if 'class="not_active_notification">Come back' in r.text:
                    print('Future sale', flush=True)
                    future_sale = True


                idx = 0
                debug_sale = 0
                debug_miss = 0

                while True:
                    idx = r.text.find('class="game_cell_data"', idx)
                    if idx == -1:
                        break
                    idx += 1


                    url = self._substr(r.text, idx, 'href="', '"')
                    print(url, flush=True)


                    if url not in active_list and url not in future_list:
                        print('Missing sale ' + url, flush=True)

                        if debug_sale == 0:
                            debug_sale = 1
                            sales_log.append(sale_url)

                        sales_log.append(url)


                    if url not in owned_list:
                        if future_sale:
                            print('Must claim later ' + url, flush=True)

                            if debug_miss == 0:
                                debug_miss = 1
                                future_log.append(sale_url)

                            future_log.append(url)

                        else:
                            game: ItchGame = ItchGame.from_api(url)
                            self.user.claim_game(game)

                            if url not in owned_list:
                                print('Not claimable ' + url, flush=True)

                                if debug_miss == 0:
                                    debug_miss = 1
                                    miss_log.append(sale_url)

                                miss_log.append(url)

            except Exception as err:
                print('Failure while checking ' + url + ' = ' + str(err), flush=True)


        self._dump_log('itch-miss.txt', miss_log)
        self._dump_log('itch-future.txt', future_log)
        self._dump_log('itch-sales.txt', sales_log)

        self._dump_log('sales-url.txt', sales_list)



    def scrape_future_sales(self):
        """Claim all unowned games. Requires login.
        Args:
            url (str): The URL to download the file from"""

        if self.user is None:
            print('You must be logged in', flush=True)
            return
        if len(self.user.owned_games) == 0:
            print('User\'s library not found in cache. Downloading it now', flush=True)
            self.user.reload_owned_games()
            self.user.save_session()

        r = self._send_web('get', 'https://itchclaim.tmbpeter.com/data/resume_index.txt')
        scrape_limit = int(r.text)


        print(f'Scraping {scrape_page} ...', flush=True)

        scrape_page -= 1
        r = None
        url = 'None'

        while True:
            try:
                scrape_page += 1

                url = f"https://itch.io/s/{scrape_page}"
                r = self._send_web('get', url, False)

                if r.status_code == 400:
                    break


# r = requests.get('http://github.com', allow_redirects=False)
# 301
# print(r.status_code, r.headers['Location'])


                r = self._send_web('get', url)

                if r.text.find('This sale ended') != -1:
                    continue

                if r.text.find('100%</strong> off') == -1:
                    continue

                sale_url = url
                print(sale_url, flush=True)

                future_sale = False
                if r.text.find('class="not_active_notification">Come back') != -1:
                    print('Future sale', flush=True)
                    future_sale = True

                idx = 0
                debug_sale = 0
                debug_miss = 0

                while True:
                    idx = r.text.find('class="game_cell_data"', idx)
                    if idx == -1:
                        break
                    idx += 1

                    url = self._substr(r.text, idx, 'href="', '"')
                    print(url, flush=True)

                    if not self._find_game(active_games, url) and not self._find_game(future_games, url):
                        print('Missing sale ' + url, flush=True)
                        with open('itch-sales.txt', 'a') as myfile:
                            if debug_sale == 0:
                                debug_sale = 1
                                print(sale_url, file=myfile, flush=True)  # Python 3.x
                            print(url, file=myfile, flush=True)  # Python 3.x


                    if not self._owns_game(url):
                        if future_sale:
                            print('Must claim later ' + url, flush=True)
                            with open('itch-future.txt', 'a') as myfile:
                                if debug_miss == 0:
                                    debug_miss = 1
                                    print(sale_url, file=myfile, flush=True)  # Python 3.x
                                print(url, file=myfile, flush=True)  # Python 3.x
                        else:
                            game: ItchGame = ItchGame.from_api(url)
                            self.user.claim_game(game)

                            if not self._owns_game(url):
                                print('Not claimable ' + url, flush=True)
                                with open('itch-miss.txt', 'a') as myfile:
                                    if debug_miss == 0:
                                        debug_miss = 1
                                        print(sale_url, file=myfile, flush=True)  # Python 3.x
                                    print(url, file=myfile, flush=True)  # Python 3.x

            except Exception as err:
                print('Failure while checking ' + url + ' = ' + str(err), flush=True)



    def _scrape_profile(self, url, main = True):
        try:
            # print(url, flush=True)

            if main == False:
                url = self._substr(url, 0, 'https://', '.itch.io')
                url = 'https://itch.io/profile/' + url

            r = self._send_web('get', url)

            str_index = 0
            while True:
                str1 = r.text.find('class="game_cell has_cover lazy_images"', str_index)
                if str1 == -1:
                    break
                str_index = str1+1

                game = ItchGame(-1)
                game.url = self._substr(r.text, str1, 'href="', '"')
                if self._owns_game(game.url):
                    continue

                # print(game.url + '  #', flush=True)
                self._claim_reward(game)

                if self.valid_reward == False:
                    self.ignore_list.add(game.url)

        except Exception as err:
            print('[_scrape_profile] Failure while checking ' + url + ' = ' + str(err), flush=True)



    def scrape_rewards(self, url: str = 'https://itchclaim.tmbpeter.com/api/active.json'):
        """Claim all unowned games. Requires login.
        Args:
            url (str): The URL to download the file from"""
            # https://www.google.com/search?q=%2B%22itch.io%22+%2B%22free+community+Copy%22
            # https://www.google.com/search?q=itch.io+%22community+copies%22

        if self.user is None:
            print('You must be logged in', flush=True)
            return
        if len(self.user.owned_games) == 0:
            print('User\'s library not found in cache. Downloading it now', flush=True)
            self.user.reload_owned_games()
            self.user.save_session()


        self.active_list = set()  # holds lines already seen
        self.ignore_list = set()
        self.valid_reward = False


        myfile = open('scrape-ignore.txt', 'r')
        for rewards_url in myfile.readlines():
            self.ignore_list.add(rewards_url)



        print(f'Scraping rewards ...', flush=True)

        myfile = open('scrape.txt', 'r')
        for rewards_url in myfile.read().splitlines():
            try:
                if rewards_url in self.active_list:
                    continue
                if rewards_url in self.ignore_list:
                    continue

                self.active_list.add(rewards_url)

                self._scrape_profile(rewards_url, True)
                self._scrape_profile(rewards_url, False)

            except Exception as err:
                print('Failure while checking ' + rewards_url + ' = ' + str(err), flush=True)


        print(f'Scraping collections ...', flush=True)

        myfile = open('scrape-list.txt', 'r')
        for rewards_url in myfile.read().splitlines():
            page = 1
            url = rewards_url + '?format=json'

            try:
                while True:
                    # print(url, flush=True)
                    r = self._send_web('get', url)
                    dat = json.loads(r.text)

                    if dat['num_items'] == 0:
                        break

                    str_index = 0
                    while True:
                        str1 = dat['content'].find('class="game_cell has_cover lazy_images"', str_index)
                        if str1 == -1:
                            break
                        str_index = str1+1

                        new_author = self._substr(dat['content'], str1, 'href="https://', '.itch.io')
                        new_profile = 'https://' + new_author + '.itch.io'


                        if new_profile in self.active_list:
                            continue
                        if new_profile in self.ignore_list:
                            continue


                        print(new_profile, flush=True)
                        self.active_list.add(new_profile)

                        self._scrape_profile(new_profile, True)
                        self._scrape_profile(new_profile, False)

                    page += 1
                    url = rewards_url + '?format=json&page=' + str(page)


            except Exception as err:
                print('[scrape_rewards] Failure while checking ' + url + ' = ' + str(err), flush=True)


        with open('scrape.txt', 'w') as myfile:
            for line in sorted(self.active_list):
                print(line, file=myfile)  # Python 3.x

        with open('scrape-ignore.txt', 'w') as myfile:
            for line in sorted(self.ignore_list):
                print(line, file=myfile)  # Python 3.x



    def auto_rating(self, url: str = 'https://itchclaim.tmbpeter.com/api/active.json'):
        """Rate one game. Requires login.
        Args:
            url (str): Game to claim"""

        if self.user is None:
            print('You must be logged in', flush=True)
            return
        if len(self.user.owned_games) == 0:
            print('User\'s library not found in cache. Downloading it now', flush=True)
            self.user.reload_owned_games()
            self.user.save_session()

        rated_games = []
        url = 'https://itch.io/library/rated?json'

        page_num = 1
        try:
            while True:
                # print(url, flush=True)

                r = self._send_web('user_get', url)
                dat = json.loads(r.text)

                if 'game_ratings' not in dat:
                    break

                extra = 0
                for item in dat['game_ratings']:
                    # print(item, flush=True)
                    rated_games.append(item['game']['id'])
                    extra += 1

                print('Reviews page #' + str(page_num) + ': added ' + str(extra) + ' games (total: ' + str(len(rated_games)) + ')', flush=True)

                if 'next_page' not in dat:
                    break

                next_url = str(dat['next_page']).replace("'", '"')
                url = 'https://itch.io/library/rated?json&next_page=' + next_url
                page_num += 1

        except Exception as err:
            print('Failure to get reviews ' + url + ' = ' + str(err), flush=True)


        for game in self.user.owned_games:
            url = game.url
            try:
                for rated in rated_games:
                    if game.id == rated:
                        url = None
                        break

                if url == None:
                    continue

                print('Rating ' + url, flush=True)

                data = {
                    'csrf_token': self.user.csrf_token,
                    'game_rating': '5'
                }

                r = self._send_web('user_post', url + '/rate?source=game&game_id=' + str(game.id), True, data)
                if 'errors' in r.text:
                    continue

                # print(r.text)
                print('Success!', flush=True)
                # return

            except Exception as err:
                print('Failure to rate ' + url + ' = ' + str(err), flush=True)



    def make_report(self, url: str = 'https://itchclaim.tmbpeter.com/api/active.json'):
        """Go through logs."""

        class _sale_item(object):
            def __init__(self):
                self.id = None
                self.list = []
                self.start = None
                self.end = None


        def _sale_add(list, item, order):
            idx = 0
            while idx < len(list):
                if order == True:
                    if item.start < list[idx].start:
                        break

                else:
                    if item.start > list[idx].start:
                        break

                idx += 1
            list.insert(idx, item)


        def _write_report(list, file):
            try:
                my_file = Path(file)

                with open(my_file, 'w') as myfile:
                    for item in list:
                        print(f"{item.id:50s} {item.start:25s} {item.end:25s}", file=myfile, flush=True)  # Python 3.x
                        for game in item.list:
                            print(game, file=myfile, flush=True)  # Python 3.x

            except Exception as err:
                print('Failed to check ' + file + ' = ' + str(err), flush=True)


        def _create_report(url, list, file, check, order):
            try:
                item = _sale_item()
                sale_url = None


                my_file = Path(url + '/' + file)
                if not my_file.exists():
                    return

                with open(my_file, 'r') as myfile:
                    for line in my_file.read_text().splitlines():
                        if line.find('itch.io/s/') != -1:
                            sale_url = line

                            if item.id != None:
                                _sale_add(list, item, order)

                            item = _sale_item()

                            r = self._send_web('get', line)
                            if r.status_code == 200:
                                item.start = self._substr(r.text, 0, '"start_date":"', '"')
                                item.end = self._substr(r.text, item.start, '"end_date":"', '"')
                            continue


                        if check == True and self._owns_game(line):
                            continue


                        r = self._send_web('get', line)

                        if r.status_code != 200:
                            continue

                        if r.text.find('A password is required to view this page') != -1:
                            continue

                        if r.text.find('<p>This asset pack is currently unavailable</p>') != -1:
                            continue

                        if r.text.find('<p>This game is currently unavailable</p>') != -1:
                            continue


                        if item.id == None:
                            item.id = sale_url
                            print(sale_url, flush=True)

                        item.list.append(line)
                        print(line, flush=True)

                    if item.id != None:
                        _sale_add(list, item, order)

                    if len(list) > 0:
                        _write_report(list, file)

            except Exception as err:
                print('Failed to check ' + url + '/' + file + ' = ' + str(err), flush=True)



        if self.user is None:
            print('You must be logged in', flush=True)
            return

        if len(self.user.owned_games) == 0:
            print('User\'s library not found in cache. Downloading it now', flush=True)
            self.user.reload_owned_games()
            self.user.save_session()

        r = self._send_web('get', 'https://itchclaim.tmbpeter.com/data/resume_index.txt')
        scrape_limit = int(r.text)

        known_sales = DiskManager.download_from_remote_cache('https://itchclaim.tmbpeter.com/api/active.json')
        # known2_sales = DiskManager.download_from_remote_cache('https://itchclaim.tmbpeter.com/api/future.json')


        with open('itch-owned.txt', 'w') as myfile:
            for game in self.user.owned_games:
                if game.url == None:
                    continue
                print(f'{game.name:60s} {game.url:50s}', file=myfile, flush=True)  # Python 3.x


        active_sales = []
        miss_sales = []
        future_sales = []

        # print(os.listdir())


        page = 0
        page -= 5000
        while page < scrape_limit:
            page += 5000
            url = 'it1h-c2ai3-zz-sales-' + str(page)

            _create_report(url, future_sales, 'itch-future.txt', True, True)
            _create_report(url, miss_sales, 'itch-miss.txt', True, False)
            _create_report(url, active_sales, 'itch-sales.txt', False, False)



    def claim_url(self, url: str = 'https://itchclaim.tmbpeter.com/api/active.json'):
        """Claim one game. Requires login.
        Args:
            url (str): Game to claim"""

        if self.user is None:
            print('You must be logged in', flush=True)
            return
        if len(self.user.owned_games) == 0:
            print('User\'s library not found in cache. Downloading it now', flush=True)
            self.user.reload_owned_games()
            self.user.save_session()

        for owned_url in [owned_game.url for owned_game in self.user.owned_games]:
            if owned_url == url:
                print(f"{game.url} already claimed", flush=True)  # Python 3.x
                return

        print(f'Attempting to claim {url}', flush=True)
        game: ItchGame = ItchGame.from_api(url)
        self.user.claim_game(game)
        self.user.claim_reward(game)



# pylint: disable=missing-function-docstring
def main():
    Fire(ItchClaim)
