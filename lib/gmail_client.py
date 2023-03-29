import imaplib
import logging
from typing import List, Tuple, Optional


class GmailClient:

    def __init__(self, username: str, password: str):
        self.imap_server = 'imap.gmail.com'
        self.email = username
        self.password = password
        self.connection = self.get_connection()

    def get_connection(self):
        connection = imaplib.IMAP4_SSL('imap.gmail.com')
        connection.login(self.email, self.password)
        connection.select('Inbox')
        return connection

    def search(self, key: str, val: str):
        result, data = self.connection.search(None, key, '"{}"'.format(val))
        return data

    def get_messages(self, search_result: List[bytes]):
        result = []
        search_result = search_result[0].split()
        for num in search_result:
            try:
                typ, data = self.connection.fetch(num, '(RFC822)')
                result.append(data)
            except Exception as err:
                logging.exception(err)

        return result

    def get_all_from_sender(self, sender: str) -> Optional[List[Tuple[bytes]]]:
        messages = self.get_messages(self.search('FROM', sender))
        return messages

    def get_unseen_from_sender(self, sender: str) -> Optional[List[Tuple[bytes]]]:
        messages = self.get_messages(self.search('UNSEEN FROM', sender))
        return messages

    def get_last_unseen_from_sender(self, sender: str) -> Optional[List[Tuple[bytes]]]:
        messages = self.get_unseen_from_sender(sender=sender)
        return messages[-1]
