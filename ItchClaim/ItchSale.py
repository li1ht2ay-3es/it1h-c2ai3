import json
import re
from typing import List
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from . import __version__


class ItchSale:
    cached_sales = {}

    def __init__(self, id: int, end: datetime = None, start: datetime = None) -> None:
        self.id: int = id
        self.end: datetime = end
        self.start: datetime = start
        self.err: str = None

        if not start or not end:
            self.get_data_online()


    def get_data_online(self):
        sale_url = f"https://itch.io/s/{self.id}"
        r = requests.get(sale_url,
                headers={
                    'User-Agent': f'ItchClaim {__version__}',
                    'Accept-Language': 'en-GB,en;q=0.9',
                    }, timeout=8)
        r.encoding = 'utf-8'

        if r.status_code == 404:
            print(f'Sale page #{self.id}: 404 Not Found')
            if r.url == sale_url:
                self.err = 'NO_MORE_SALES_AVAILABLE'
            else:
                self.err = '404_NOT_FOUND'
            return

        # Used by DiskManager.get_one_sale()
        self.soup = BeautifulSoup(r.text, 'html.parser')

        date_format = '%Y-%m-%dT%H:%M:%SZ'
        sale_data = json.loads(re.findall(r'new I\.SalePage.+, (.+)\);I', r.text)[0])
        self.start = datetime.strptime(sale_data['start_date'], date_format)
        self.end = datetime.strptime(sale_data['end_date'], date_format)

        if self.id != sale_data['id']:
            raise ValueError(f'Sale ID mismatch in parsed <script> tag. Excepted {self.id}')


    def serialize(self):
        return {
            'id': self.id,
            'start': int(self.start.timestamp()),
            'end': int(self.end.timestamp()),
        }


    @classmethod
    def from_dict(cls, dict: dict):
        id = dict['id']
        try:
            start = datetime.fromtimestamp(dict['start'])
            end = datetime.fromtimestamp(dict['end'])
            return ItchSale(id, start=start, end=end)
        except KeyError:
            # Data gathered before v1.3 may not contain all fields
            print(f'Refreshing missing data for sale {id}')
            if (id in ItchSale.cached_sales):
                print('Found in cache')
                return ItchSale.cached_sales[id]
            sale = ItchSale(id)

            # If the sale was removed (page returned 404) give fill it with data
            if sale.err:
                if not 'end' in dict:
                    sale.start = datetime.fromtimestamp(dict['start'])
                    sale.end = sale.start
                    print(f'Warning: {id} was removed from itch.io. Setting it\'s end date to it\'s start date')
                elif not 'start' in dict:
                    sale.end = datetime.fromtimestamp(dict['end'])
                    sale.start = sale.end
                    print(f'Warning: {id} was removed from itch.io. Setting it\'s start date to it\'s end date')
            
            # Make ItchGame save the updates to the disk
            sale.err = 'STATUS_UPDATED'
            ItchSale.cached_sales[id] = sale
            return sale


    @staticmethod
    def serialize_list(list: List):
        return [ sale.serialize() for sale in list ]


    @property
    def is_active(self):
        if datetime.now() < self.end:
            return True
        return False


    @property
    def is_upcoming(self):
        return datetime.now() < self.start
