# -*- coding: utf-8 -*-
###
# Copyright (c) 2013, Pierre-Francois Carpentier
# All rights reserved.
#
###


from __future__ import unicode_literals
from slackclient import SlackClient
import os
import time
from lxml import etree
import threading
from hashlib import md5
import unicodedata
import datetime
import itertools
import inspect
import re

import sys
import collections
import copy
import logging
import threading

class SqliteSeLogerDB(object):
    """This Class is the backend of the plugin,
    it handles the database, its creation, its updates,
    it also provides methods to get the ads information
    """

    def __init__(self, log, filename='db.seloger'):
        self.dbs = {} 
        self.filename = filename
        self.log = log
        #the elements we get from the xml
        self.val_xml = (
            'idTiers', 
            'idAnnonce',
            'idPublication', 
            'idTypeTransaction', 
            'idTypeBien',
            'dtFraicheur', 
            'dtCreation', 
            'titre', 
            'libelle', 
            'proximite', 
            'descriptif', 
            'prix',
            'prixUnite', 
            'prixMention', 
            'nbPiece', 
            'nbChambre', 
            'surface', 
            'surfaceUnite', 
            'idPays', 
            'pays', 
            'cp', 
            'ville', 
            'nbPhotos',
            'firstThumb',
            'permaLien',
            'latitude',
            'longitude',
            'llPrecision'
        ) 
        self.val_xml_count = len(self.val_xml)
        #the primary key of the results table
        self.primary_key = 'idAnnonce'

    def _dict_factory(self, cursor, row):
        """just a small trick to get returns from the
        searches inside the database as dictionnaries
        """
        d = {}
        for idx,col in enumerate(cursor.description):
            d[col[0]] = row[idx]
        return d

    def close(self):
        """function closing the database cleanly
        """
        for db in self.dbs.itervalues():
            db.close()

    def _getDb(self):
        """this function returns a database connexion, if the
        database doesn't exist, it creates it.
        no argument.
        """
        try:
            import sqlite3
        except ImportError:
            raise Exception('You need to have sqlite3 installed to ' \
                                   'use SeLoger.')
        filename = 'db.seloger'

        if filename in self.dbs:
            return self.dbs[filename]
        if os.path.exists(filename):
            self.dbs[filename] = sqlite3.connect(
                filename, check_same_thread = False
                )

            return self.dbs[filename]
        db = sqlite3.connect(filename, check_same_thread = False)
        self.dbs[filename] = db
        cursor = db.cursor()

        #initialisation of the searches table 
        #(contains the searches entered by each user) 
        #search_id: the id of the search 
        #owner_id: the id of the user who entered the search
        #flag_active: a flag set to 1 when the search is active, 
        #             0 when it's not (not in use)
        #cp: the postal code
        #min_surf: minimum surface of the annonce
        #max_price: maximum rent
        #ad_type: type of the ad (1 -> rent, 2 -> sell)
        cursor.execute("""CREATE TABLE searches (
                          search_id TEXT PRIMARY KEY,
                          owner_id TEXT, 
                          flag_active INTEGER,
                          cp TEXT,
                          min_surf TEXT,
                          max_price TEXT,
                          ad_type TEXT,
                          nb_pieces TEXT,
                          UNIQUE (search_id) ON CONFLICT IGNORE)"""
                      )

        #mapping between a search result and a user (n to n mapping)
        #idAnnonce: the id of on annonce
        #owner_id: the id of an owner
        #flag_shown: a flag set to 0 when the annonce was already 
        #           presented to owner_id, 0 if not
        cursor.execute("""CREATE TABLE map (
                          uniq_id TEXT PRIMARY KEY,
                          idAnnonce TEXT,
                          flag_shown INT,
                          ad_type TEXT,
                          owner_id TEXT,
                          UNIQUE (uniq_id) ON CONFLICT IGNORE)"""
                      )

        #generation of the results table (contains the ads info)
        #first: generate the string of fields from self.val_xml
        table_results = ''
        for val in self.val_xml:
            if val == self.primary_key:
                table_results = table_results + val \
                                + ' TEXT PRIMARY KEY, '
            else:
                table_results = table_results + val \
                                + ' TEXT, '

        #finally: creation of the table
        cursor.execute("""CREATE TABLE results (
                          %s
                          UNIQUE (idAnnonce)ON CONFLICT IGNORE)""" % 
                          table_results 
                      )

        db.commit()
        self.log.info('database %s created',filename)
        return db

    def _get_annonce(self, idAnnonce):
        """backend function getting the information of one ad
           arg 1: the ad unique ID ('idAnnonce') 
        """
        db = self._getDb()
        db.row_factory = self._dict_factory
        cursor = db.cursor()
        cursor.execute(
            """SELECT * FROM results WHERE idAnnonce = (?)""",
            (idAnnonce, )
            )
        return cursor.fetchone()

    def _search_seloger(self, cp, min_surf, max_price, ad_type, owner_id, nb_pieces_min):
        """entry function for getting the ads on seloger.com
        arg 1: the postal code
        arg 2: the minimal surface
        arg 3: the maximum rent
        arg 4: type of the add (1 -> location, 2 -> sell) 
        arg 5: the owner_id of the search (the user making the search)
        arg 6: nb_pieces_min, minimum number of rooms 

        """
        owner_id.lower() 
        #the first url for the search
        nb_pieces_search = ','.join([str(x) for x in range(int(nb_pieces_min), 20)])
        url = 'http://ws.seloger.com/search.xml?cp=' + cp + \
        '&idqfix=1&idtt=' + ad_type + '&idtypebien=1,2&pxmax=' + max_price + \
        '&surfacemin=' + min_surf + '&nb_pieces=' + nb_pieces_search

        #we search all the pages 
        #(the current page gives the next if it exists)
        while url is not None:
                url = self._get(url, ad_type, owner_id)

    def _get(self, url, ad_type, owner_id):
        """
        function getting the xml pages  and putting
        the results inside the database
        arg 1: the url giving the nice xml
        arg 2: the owner_id of the search
        """
        owner_id.lower() 
        db = self._getDb()
        cursor = db.cursor()

        #we try to load the xml page
        try:
            tree = etree.parse(url)
        except:
            #if we have some troubles loading the page
            self.log.warning('could not download %s',url)
            return None
        
        #we get the info from the xml
        root = tree.getroot()
        annonces = root.find('annonces')

        if annonces is None:
            return None

        for annonce in annonces:
            values_list=[]
            for val in self.val_xml:
                #if the value exists we put it in the db
                #if it doesn't we put "Unknown"
                if annonce.find(val) is None or annonce.find(val).text is None:
                    values_list.append(u'Unknown')
                else:
                    values_list.append(str(annonce.find(val).text))

            # ignore ads that are more than 30 days old
            d = datetime.datetime.strptime(annonce.find('dtCreation').text, '%Y-%m-%dT%H:%M:%S')
            n = datetime.datetime.now()
            delta = n.date() - d.date()

            # inserting the ad information inside the table
            # ignore Viager
            if not re.match(r'.*[Vv]iager.*', annonce.find('descriptif').text) \
		and not re.match(r'.*/viagers/.*', annonce.find('permaLien').text) \
		and delta.days < 30:
                cursor.execute(
                        "INSERT INTO results VALUES (" + \
                        ','.join(itertools.repeat('?', self.val_xml_count)) + ")",
                        tuple(values_list)
                        )

                annonce_id = annonce.find('idAnnonce').text

                #calcul of the uniq id for the mapping between 
                #the searcher and the ad
                uniq_id = md5((owner_id + annonce_id).encode('utf-8')).hexdigest()

                #inserting the new ad inside map
                cursor.execute("INSERT INTO map VALUES (?,?,?,?,?)",\
                        (uniq_id, annonce_id, '1', ad_type, owner_id))
                db.commit()

        #if there is another page, we return it, we return None otherwise
        if tree.xpath('//recherche/pageSuivante'):
            return  tree.xpath('//recherche/pageSuivante')[0].text
        else:
            return None

    def _get_date(self, ad):
        """
        function getting the creation date of an ad
        arg 1: ad
        """
        return ad['dtCreation']


    def add_search(self, owner_id, cp, min_surf, max_price, ad_type, nb_pieces_min):
        """this function adds a search inside the database
        arg 1: te owner_id of the new search
        arg 2: the postal code of the new search
        arg 3: the minimal surface
        arg 4: the maximum price
        arg 4: the minimum number of room
        """
        owner_id.lower() 
        db = self._getDb()
        cursor = db.cursor()
        
        #calcul of a unique ID
        search_id = md5((owner_id + cp + min_surf + max_price + ad_type + nb_pieces_min).encode('utf-8')).hexdigest()

        #insertion of the new search parameters
        cursor.execute("INSERT INTO searches VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (search_id, owner_id, '1', cp, min_surf, max_price, ad_type, nb_pieces_min)
            )

        db.commit()

        self.log.info('%s has added a new search', owner_id)
        return search_id

    def do_searches(self):
        """This function plays the searches of every user,
        and puts the infos inside the database.
        no argument
        """
        self.log.info('begin refreshing database')
        db = self._getDb()
        db.row_factory = self._dict_factory
        cursor = db.cursor()
        #we select all the active searches
        cursor.execute("SELECT * FROM searches WHERE flag_active = 1")

        #for each searches we query seloger.com
        for row in cursor.fetchall():
            self._search_seloger(
                row['cp'],row['min_surf'],row['max_price'],row['ad_type'],row['owner_id'],row['nb_pieces']
                )
        self.log.info('end refreshing database')

    def disable_search(self, search_id, owner_id):
        """ this function disable a search
        arg 1: the unique id of the search
        agr 2: the owner_id of the search
        """
        self.log.info('disabling search %s',search_id)
        db = self._getDb()
        db.row_factory = self._dict_factory
        cursor = db.cursor()
        #we delete the given search of the given user
        cursor.execute(
            "DELETE FROM searches WHERE search_id = (?) AND owner_id = (?)",
            (search_id, owner_id)
            )
        db.commit()
        self.log.info('%s has deleted search %s', owner_id, search_id)

    def get_search(self, owner_id):
        """ this function returns the search of a given user
        arg 1: the owner_id
        """
        self.log.info('printing search list of %s', owner_id)
        owner_id.lower() 
        db = self._getDb()
        db.row_factory = self._dict_factory
        cursor = db.cursor()
        #we get all the searches of the given user
        cursor.execute(
            "SELECT * FROM searches WHERE owner_id = (?) AND flag_active = 1",
            (owner_id, )
            )
        self.log.info('%s has queried his searches', owner_id)

        return cursor.fetchall()

    def get_new(self):
        """ this function returns the ads not already printed
        and marks them as "printed".
        no argument
        """
        db = self._getDb()
        db.row_factory = self._dict_factory
        cursor = db.cursor()
        #we get all the new ads
        cursor.execute("SELECT * FROM map WHERE flag_shown = 1")

        return_annonces=[]
        for row in cursor.fetchall():
            uniq = row['uniq_id']
            #we mark the ad as "read"
            cursor.execute(
                """UPDATE map SET flag_shown = 0 WHERE uniq_id = (?)""",
                (uniq, )
                )
            #we get the infos of the ad
            result = self._get_annonce(row['idAnnonce'])
            #we ad in the result the name of the owner
            result['owner_id'] = row['owner_id']
            return_annonces.append(result)

        db.commit()

        #we sort the ads by date
        return_annonces.sort(key=self._get_date)
        #we get the number of new ads
        number_of_new_ads = str(len(return_annonces))
        self.log.info('printing %s new ads', number_of_new_ads)
        #we return the ads
        return return_annonces

    def get_all(self, owner_id, pc='all', ad_type='1'):
        """ this function returns all the ads of a given user and postal code
        arg1: the owner id
        arg2: the postal code
        """
        db = self._getDb()
        db.row_factory = self._dict_factory
        cursor = db.cursor()
        #we get all the ads of a given user
        cursor.execute("SELECT * FROM map WHERE owner_id = (?) AND ad_type = (?)",
                (owner_id, ad_type)
                )

        return_annonces=[]
        for row in cursor.fetchall():
            uniq = row['uniq_id']

            #we get the infos of the ad
            result = self._get_annonce(row['idAnnonce'])
            #we ad in the result the name of the owner
            result['owner_id'] = row['owner_id']
            #we ad it only if we query all the ads 
            #or it matches the postal code
            if pc == 'all' or result['cp'] == pc:
                return_annonces.append(result)

        #we get the number of ads
        number_of_ads = str(len(return_annonces))
        self.log.info('getting %s ads', number_of_ads)
        #we return the ads
        return return_annonces


class SeLoger():
    """This plugin search and alerts you in query if 
    new ads are available.
    Use "sladd" for a new search.
    Use "sllist" to list you current search.
    Use "sldisable" to remove an old search."""

    def __init__(self, sc):
        self.log = logging.getLogger()
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        self.log.addHandler(handler)
        self.backend = SqliteSeLogerDB(self.log)
        self.gettingLockLock = threading.Lock()
        self.locks = {}
        self.sc = sc
        self.graph = Pyasciigraph()
        self._start_bg()
        
    def _send_msg(self, msg, to, private):
        self.sc.api_call(
            'chat.postMessage',
            channel=to,
            text=msg,
            username='selogerbot',
            as_user=False
        )

    ### the external methods

    def slhelp(self, event):
        """usage: slhelp
        display the help for this module
        """
        help_content= {
            'slhelp': [None, 'Help for this module'],
            'sladdrent': ['<postal code> <min surface> <max price> <min_num_room>', 'Register  a new rent search'],
            'sladdbuy': ['<postal code> <min surface> <max price> <min_num_room>', 'Register a new buy search'],
            'sllist': [None, 'List your active searches:'],
            'sldisable': ['<search ID>', 'Remove the given search (use sllist to get <search ID>)'],
            'slstatrent': ['<postal code|\'all\'>', 'Print some stats about \'rent\' searches'],
            'slstatbuy': ['<postal code|\'all\'>', 'Print some stats about \'buy\'  searches'],
        }
        msg = 'Action I can provide:\n'
        for cmd in help_content:
            if help_content[cmd][0]:
                msg += "* *%s* _%s_: %s\n" % (cmd, help_content[cmd][0], help_content[cmd][1])
            else:
                msg += "* *%s*: %s\n" % (cmd, help_content[cmd][1])
        self.sc.api_call(
            'chat.postMessage',
            channel=event['channel'],
            text=msg,
            username='selogerbot',
            as_user=False
        )

    def sladdrent(self, pc: int, min_surf: int, max_price: int, nb_pieces:int,
event):
        """usage: sladd_rent <postal code> <min surface> <max price> <nb_pieces>
        Adds a new rent search for you ( /!\ many messages in the first batch )
        """
        user = event['user']
        self._addSearch(str(user), str(pc), str(min_surf), str(max_price), '1', str(nb_pieces))
        msg='Done sladd'
        self.sc.api_call(
            'chat.postMessage',
            channel=event['channel'],
            text=msg,
            username='selogerbot',
            as_user=False
        )


    def sladdbuy(self, pc: int, min_surf: int, max_price: int, nb_pieces:int, event):
        """usage: sladd_buy <postal code> <min surface> <max price> <nb_pieces>
        Adds a new buy search for you ( /!\ many messages in the first batch )
        """
        user = event['user']
        self._addSearch(str(user), str(pc), str(min_surf), str(max_price), '2',
                str(nb_pieces))
        msg='Done sladd'
        self.sc.api_call(
            'chat.postMessage',
            channel=event['channel'],
            text=msg,
            username='selogerbot',
            as_user=False
        )

    def sldisable(self, id_search: str, event):
        """usage: sldisable <id_search>
        Disables a search
        """
        user = event['user']
        self._disableSearch(user, id_search)
        msg='Done sldisable'
        self.sc.api_call(
            'chat.postMessage',
            channel=event['channel'],
            text=msg,
            username='selogerbot',
            as_user=False
        )

    def sllist(self, event):
        """usage: sllist
        list all your searches
        """
        user = event['user']
        self._listSearch(user, event)
        msg='Done sllist in *slackbot* channel'
        self.sc.api_call(
            'chat.postMessage',
            channel=event['user'],
            text=msg,
            username='selogerbot',
            as_user=False
        )

    def slstatrent(self, pc: str, event):
        """usage: slstatrent <postal code|'all'>
        give you some stats about your rent searches.
        Specify 'all' (no filter), or a specific postal code
        """
        user = event['user']
        self._gen_stat_rooms(user, pc, '1')
        self._gen_stat_surface(user, pc, '1')
        msg='Done slstatrent'
        self._send_msg(msg,to=user,private=True)

    def slstatbuy(self, pc: str, event):
        """usage: slstatbuy <postal code|'all'>
        give you some stats about your buy searches.
        Specify 'all' (no filter), or a specific postal code
        """
        user = event['user']
        self._gen_stat_rooms(user, pc, '2')
        self._gen_stat_surface(user, pc, '2')
        msg='Done slstatbuy'
        self._send_msg(msg,to=user,private=True)

    ### The internal methods
    def _print_stats(self, user, stats):
        """ small function to print a list of line in different color
        """

        #empty line for lisibility
        msg = '```'

        #list of colors we use (order matters)
        colors = [ 15, 14, 10, 3, 7, 2, 6, 5 ]  
        colors_len = len(colors)
        color = 0

        for line in stats:
            msg += '\n' + line
        msg += '```'
        self._send_msg(msg,to=user,private=True)


    def _gen_stat_rooms(self, user, pc, ad_type):
        """internal function generating stats about the number of rooms
        """
        #we get all the ads of the user (with a filter on the postal code)
        ads = self.backend.get_all(user, pc, ad_type)

        #if we have nothing to make stats on
        if len(ads) == 0:
            msg = 'no stats about number of rooms available'
            self._send_msg(msg,to=user,private=True)
            return

        number_ads_by_room = {}
        surface_by_room = {}
        price_by_room = {}
        surface_by_room = {}

        list_surface = []
        list_price = []
        list_number = []

        for ad in ads:
            rooms = ad['nbPiece']
            #we increment 'n (rooms)' 
            if rooms in number_ads_by_room:
                number_ads_by_room[rooms] += 1
            else:
                number_ads_by_room[rooms] = 1

            #we add the price to the corresponding field
            if rooms in price_by_room:
                price_by_room[rooms] += float(ad['prix'])
            else:
                price_by_room[rooms] = float(ad['prix'])

            #we add the surface to the corresponding field
            if rooms in surface_by_room:
                surface_by_room[rooms] += float(ad['surface'])
            else:
                surface_by_room[rooms] = float(ad['surface'])
    
        #we generate the list of tuples
        for rooms in sorted(surface_by_room, key=int):

            #the list for number of ads by number of rooms
            list_number.append(( rooms  + ' room(s)',
                number_ads_by_room[rooms]))

            #calcul of the avrage surface for this number of rooms
            surface_by_room[rooms] = surface_by_room[rooms] \
                    / number_ads_by_room[rooms]

            list_surface.append(( rooms  + ' room(s)', 
                int(surface_by_room[rooms]))) 


            #calcul of the avrage price for this number of rooms
            price_by_room[rooms] = price_by_room[rooms] \
                / number_ads_by_room[rooms] 

            list_price.append(( rooms  + ' room(s)', 
                int(price_by_room[rooms])))

        #we print all that
        graph_number = self.graph.graph(u'number of ads by room', list_number)
        self._print_stats(user, graph_number)

        graph_surface =  self.graph.graph(u'surface by room', list_surface)
        self._print_stats(user, graph_surface)

        graph_price = self.graph.graph(u'price by room', list_price)
        self._print_stats(user, graph_price)

    def _get_step(self, ads, id_row, number_of_steps):
        """internal function generating a step for numerical range
        """
        mini = float(ads[0][id_row])
        maxi = float(ads[0][id_row])

        for ad in ads:
            value = float(ad[id_row]) 
            if value > maxi:
                maxi = value
            if value < mini:
                mini = value
        return max(1, int((maxi - mini) / number_of_steps))

    def _gen_stat_surface(self, user, pc, ad_type):
        """internal function generating stats about the surface
        """
        #we get all the ads of the user (with a filter on the postal code)
        ads = self.backend.get_all(user, pc, ad_type)
        #if we have nothing to make stats on
        if len(ads) == 0:
            msg = 'no stats about surface available'
            self._send_msg(msg,to=user,private=True)
            return

        number_ads_by_range = {}
        rent_by_range = {}
        price_by_range = {}


        list_rent = []
        list_price = []
        list_number = []

        number_of_steps = 7
        #we calcul the step of the range (max step is 5)
        step = min(self._get_step(ads, 'surface', number_of_steps), 5)

        for ad in ads:
            surface_range = str(int(float(ad['surface']) / step))

            #we count the number of ads by range
            if surface_range in number_ads_by_range:
                number_ads_by_range[surface_range] += 1
            else:
                number_ads_by_range[surface_range] = 1

            #we add the rent to the corresponding range
            if surface_range in rent_by_range:
                rent_by_range[surface_range] += float(ad['prix'])
            else:
                rent_by_range[surface_range] = float(ad['prix'])
    
            #we add the rent per square meter to the corresponding range
            if surface_range in price_by_range:
                price_by_range[surface_range] += float(ad['prix']) \
                        / float(ad['surface'])
            else:
                price_by_range[surface_range] = float(ad['prix']) \
                        / float(ad['surface'])
 
        #we generate the list of tuples to print
        for surface_range in sorted(number_ads_by_range, key=int):
            #calcul of the label
            label = str( int(surface_range) * step) + \
                    ' to ' +\
                    str((int(surface_range) + 1) * step)

            #number of ads by range
            list_number.append(( label,
                number_ads_by_range[surface_range]))

            #calcul of mid rent by range
            mid_rent = int(rent_by_range[surface_range] \
                    / number_ads_by_range[surface_range])

            list_rent.append(( label,
                mid_rent))

            #calcul of mid rent per square meter by range
            mid_price = int(price_by_range[surface_range] \
                    / number_ads_by_range[surface_range])

            list_price.append(( label,
                mid_price))

        #we print all these stats
        graph_number = self.graph.graph(u'number of ads by surface range', list_number)
        self._print_stats(user, graph_number)

        graph_rent =  self.graph.graph(u'price by surface range', list_rent)
        self._print_stats(user, graph_rent)

        graph_price = self.graph.graph(u'price per square meter by surface range', list_price)
        self._print_stats(user, graph_price)
 
 
    def _start_bg(self):
        """black supybot magic... at least for me
        """
        t = threading.Thread(None,self._print_loop, None,)
        t.start()
        print("starting")

    def _update_db(self):
        """direct call to do_search from the backend class
        it gets the new ads from SeLoger
        """
        self.backend.do_searches()

    def _acquireLock(self, url, blocking=True):
        """Lock handler for the threads
        """
        try:
            self.gettingLockLock.acquire()
            try:
                lock = self.locks[url]
            except KeyError:
                lock = threading.RLock()
                self.locks[url] = lock
            return lock.acquire(blocking=blocking)
        finally:
            self.gettingLockLock.release()

    def _releaseLock(self, url):
        """Lock handler for the threads
        """
        self.locks[url].release()

    def _print_loop(self):
        """This function updates the database 
        and prints any new results to each user
        """
        while True:
            if self._acquireLock('print', blocking=False):
                print('Get new ads')
                self._update_db()
                print('Call seloger for new ads')
                ads = self.backend.get_new()
                print('Start printing')
                total = len(ads)
                counter = 1
                for ad in ads:
                    self._print_ad(ad, counter, total)
                    counter += 1
                print('End printing')
                #we search every 5 minutes
                time.sleep(30)
                self._releaseLock('print')

    def _reformat_date(self, date):
        """small function reformatting the date from SeLoger
        """
        d = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%S')
        return  d.strftime('%d/%m/%Y %H:%M')

    def _print_ad(self,ad, counter, total):
        """this function prints one ad
        """
        #user needs to be an ascii string, not unicode
        user = str(ad['owner_id'])

        #empty line for lisibility
        msg = 'new ad %d/%d' % (counter, total)
        #self._send_msg(msg,to=user,private=True)

        #printing the pric, number of rooms and surface
        price = 'Prix: ' + ad['prix'] + ad['prixUnite']
        rooms  = 'Pieces: ' + ad['nbPiece']
        surface = 'Surface: ' + ad['surface'] + ad['surfaceUnite']
        msg += '\n' + price + ' | ' + rooms + ' | ' + surface
        #self._send_msg(msg,to=user,private=True)

        #printing the city, the postal code and date of the ad
        city = 'Ville: ' + ad['ville']
        cp = 'Code postal: ' + ad['cp']
        date = 'Date ajout: ' + self._reformat_date(ad['dtCreation'])

        msg += '\n' + city + ' | ' + cp + ' | ' + date
        #self._send_msg(msg,to=user,private=True)

        #printing a googlemaps url to see where it is (data not accurate)
        msg += '\n' + 'Localisation: https://maps.google.com/maps?q=' \
            + ad['latitude'] + '+' + ad['longitude']
        #self._send_msg(msg,to=user,private=True)

        #printing "Proximite" info
        msg += '\n' + 'Proximite: ' + ad['proximite']
        #self._send_msg(msg,to=user,private=True)

        #print the description
        msg += '\n' + u'Description: ' + re.sub(r'\n', r' ', ad['descriptif'])

        #\n creates some mess when we print them, so we remove them.
        #msg = re.sub(r'\n', r' ', msg)
        #self._send_msg(msg,to=user,private=True)

        #printing the permanent link of the ad
        msg += '\n' + 'Lien: ' + ad['permaLien']
        self._send_msg(msg,to=user,private=True)

        #one more time, an empty line for lisibility
        #msg =  ' '
        #self._send_msg(msg,to=user,private=True)

        self.log.debug('printing ad %s of %s ', ad['idAnnonce'], user)
 
    def _addSearch(self, user, pc, min_surf, max_price, ad_type, nb_pieces):
        """this function adds a search"""
        self.backend.add_search(user, pc, min_surf, max_price, ad_type,
                nb_pieces)

    def _disableSearch(self, user, id_search):
        """this function disables a search"""
        self.backend.disable_search(id_search,user)

    def _listSearch(self, user, event):
        """this function list the current searches of a user"""
        searches = self.backend.get_search(user)
        msg = ''
        for search in searches:
            id_search = "ID: " + search['search_id']
            surface = "Surface >= " + search['min_surf']
            loyer = "Loyer/Prix <= " + search['max_price']
            cp = "Code Postal == " + search['cp']
            if search['ad_type'] == '2':
                ad_type = '2 (achat)'
            elif search['ad_type'] == '1':
                ad_type = '1 (location)'
            else:
                ad_type = search['ad_type'] + ' (inconnu)'
            type_ad = "Type d'annonce == " + ad_type
            nb_pieces = "Pieces >= " + search['nb_pieces']
            msg += '\n' + id_search + " | " + surface + " | " + loyer + " | " + cp + " | " + type_ad + " | " + nb_pieces
        self.sc.api_call(
            'chat.postMessage',
            channel=event['user'],
            text=msg,
            username='selogerbot',
            as_user=False
        )

Class = SeLoger


class Pyasciigraph:

    def __init__(self, line_length=79,
                 min_graph_length=50,
                 separator_length=2,
                 force_max_value=None,
                 graphsymbol=None,
                 multivalue=True,
                 human_readable=None,
                 float_format='{0:.0f}',
                 titlebar='#'
                 ):
        """Constructor of Pyasciigraph

        :param line_length: the max number of char on a line
          if any line cannot be shorter,
          it will go over this limit.
          Default: 79
        :type line_length: int
        :param min_graph_length: the min number of char
          used by the graph itself.
          Default: 50
        :type min_graph_length: int
        :param force_max_value: if provided, force a max value in order to graph
          each line with respect to it (only taking the actual max value if
          it is greater).
        :type: force_max_value: int
        :param separator_length: the length of field separator.
          Default: 2
        :type separator_length: int
        :param graphsymbol: the symbol used for the graph bar.
          Default: '█'
        :type graphsymbol: str or unicode (length one)
        :param multivalue: displays all the values if multivalued when True.
          displays only the max value if False
          Default: True
        :type multivalue: boolean
        :param human_readable: trigger human readable display (K, G, etc)
          Default: None (raw value display)

          * 'si' for power of 1000

          * 'cs' for power of 1024

          * any other value for raw value display)

        :type human_readable: string (si, cs, none)
        :param float_format: formatting of the float value
          Default: '{0:.0f}' (convert to integers).
          expample: '{:,.2f}' (2 decimals, '.' to separate decimal and int,
          ',' every three power of tens).
        :param titlebar: sets the character(s) for the horizontal title bar
          Default: '#'
        :type titlebar: string
        """

        self.line_length = line_length
        self.separator_length = separator_length
        self.min_graph_length = min_graph_length
        self.max_value = force_max_value
        self.float_format = float_format
        self.titlebar = titlebar
        if graphsymbol is None:
            self.graphsymbol = self._u('█')
        else:
            self.graphsymbol = graphsymbol
        if self._len_noansi(self.graphsymbol) != 1:
            raise Exception('Bad graphsymbol length, must be 1',
                            self._len_noansi(self.graphsymbol))
        self.multivalue = multivalue
        self.hsymbols = [self._u(''), self._u('K'), self._u('M'),
                         self._u('G'), self._u('T'), self._u('P'),
                         self._u('E'), self._u('Z'), self._u('Y')]

        if human_readable == 'si':
            self.divider = 1000
        elif human_readable == 'cs':
            self.divider = 1024
        else:
            self.divider = None

    @staticmethod
    def _len_noansi(string):
        l = len(re.sub('\x1b[^m]*m', '', string))
        return l

    def _trans_hr(self, value):

        if self.divider is None:
            return self.float_format.format(value)
        vl = value
        for hs in self.hsymbols:
            new_val = vl / self.divider
            if new_val < 1:
                return self.float_format.format(vl) + hs
            else:
                vl = new_val
        return self.float_format.format(vl * self.divider) + hs

    @staticmethod
    def _u(x):
        """Unicode compat helper
        """
        if sys.version < '3':
            return x + ''.decode("utf-8")
        else:
            return x

    @staticmethod
    def _color_string(string, color):
        """append color to a string + reset to white at the end of the string
        """
        if color is None:
            return string
        else:
            return color + string + '\033[0m'

    def _get_thresholds(self, data):
        """get various info (min, max, width... etc)
        from the data to graph.
        """
        all_thre = {}
        all_thre['value_max_length'] = 0
        all_thre['info_max_length'] = 0
        all_thre['max_pos_value'] = 0
        all_thre['min_neg_value'] = 0

        if self.max_value is not None:
            all_thre['max_pos_value'] = self.max_value

        # Iterate on all the items
        for (info, value, color) in data:
            totalvalue_len = 0

            # If we have a list of values for the item
            if isinstance(value, collections.Iterable):
                icount = 0
                maxvalue = 0
                minvalue = 0
                for (ivalue, icolor) in value:
                    if ivalue < minvalue:
                        minvalue = ivalue
                    if ivalue > maxvalue:
                        maxvalue = ivalue
                    # if we are in multivalued mode, the value string is
                    # the concatenation of the values, separeted by a ',',
                    # len() must be computed on it
                    # if we are not in multivalued mode, len() is just the
                    # longer str(value) len ( /!\, value can be negative,
                    # which means that it's not simply len(str(max_value)))
                    if self.multivalue:
                        totalvalue_len += len("," + self._trans_hr(ivalue))
                    else:
                        totalvalue_len = max(totalvalue_len, len(self._trans_hr(ivalue)))

                if self.multivalue:
                    # remove one comma if multivalues
                    totalvalue_len = totalvalue_len - 1

            # If the item only has one value
            else:
                totalvalue_len = len(self._trans_hr(value))
                maxvalue = value
                minvalue = value

            if minvalue < all_thre['min_neg_value']:
                all_thre['min_neg_value'] = minvalue

            if maxvalue > all_thre['max_pos_value']:
                all_thre['max_pos_value'] = maxvalue

            if self._len_noansi(info) > all_thre['info_max_length']:
                all_thre['info_max_length'] = self._len_noansi(info)

            if totalvalue_len > all_thre['value_max_length']:
                all_thre['value_max_length'] = totalvalue_len

        return all_thre

    def _gen_graph_string(
            self, value, max_value, min_neg_value, graph_length, start_value_pos, color):
        """Generate the bar + its paddings (left and right)
        """
        def _gen_graph_string_part(
                value, max_value, min_neg_value, graph_length, color):

            all_width = max_value + abs(min_neg_value)

            if all_width == 0:
                bar_width = 0
            else:
                bar_width = int(abs(float(value)) * float(graph_length) / float(all_width))

            return (Pyasciigraph._color_string(
                    self.graphsymbol * bar_width,
                color),
                bar_width
                )

        all_width = max_value + abs(min_neg_value)

        if all_width == 0:
            bar_width = 0
            neg_width = 0
            pos_width = 0
        else:
            neg_width = int(abs(float(min_neg_value)) * float(graph_length) / float(all_width))
            pos_width = int(abs(max_value) * graph_length / all_width)

        if isinstance(value, collections.Iterable):
            accuvalue = 0
            totalstring = ""
            totalsquares = 0

            sortedvalue = copy.deepcopy(value)
            sortedvalue.sort(reverse=False, key=lambda tup: tup[0])
            pos_value = [x for x in sortedvalue if x[0] >= 0]
            neg_value = [x for x in sortedvalue if x[0] < 0]

            # for the negative values, we build the bar + padding from 0 to the left
            for i in reversed(neg_value):
                ivalue = i[0]
                icolor = i[1]
                scaled_value = ivalue - accuvalue
                (partstr, squares) = _gen_graph_string_part(
                    scaled_value, max_value, min_neg_value, graph_length, icolor)
                totalstring = partstr + totalstring
                totalsquares += squares
                accuvalue += scaled_value

            # left padding
            totalstring = Pyasciigraph._u(' ') * (neg_width - abs(totalsquares)) + totalstring

            # reset some counters
            accuvalue = 0
            totalsquares = 0

            # for the positive values we build the bar from 0 to the right
            for i in pos_value:
                ivalue = i[0]
                icolor = i[1]
                scaled_value = ivalue - accuvalue
                (partstr, squares) = _gen_graph_string_part(
                    scaled_value, max_value, min_neg_value, graph_length, icolor)
                totalstring += partstr
                totalsquares += squares
                accuvalue += scaled_value

            # right padding
            totalstring += Pyasciigraph._u(' ') * (start_value_pos - neg_width - abs(totalsquares))
            return totalstring
        else:
            # handling for single value item
            (partstr, squares) = _gen_graph_string_part(
                value, max_value, min_neg_value, graph_length, color)
            if value >= 0:
                return Pyasciigraph._u(' ') * neg_width + \
                        partstr + \
                        Pyasciigraph._u(' ') * (start_value_pos - (neg_width + squares))
            else:
                return Pyasciigraph._u(' ') * (neg_width - squares) +\
                        partstr +\
                        Pyasciigraph._u(' ') * (start_value_pos - neg_width)


    def _gen_info_string(self, info, start_info_pos, line_length):
        """Generate the info string + padding
        """
        number_of_space = (line_length - start_info_pos - self._len_noansi(info))
        return info + Pyasciigraph._u(' ') * number_of_space

    def _gen_value_string(self, value, min_neg_value, color, start_value_pos, start_info_pos):
        """Generate the value string + padding
        """
        icount = 0
        if isinstance(value, collections.Iterable) and self.multivalue:
            for (ivalue, icolor) in value:
                if icount == 0:
                    # total_len is needed because the color characters count
                    # with the len() function even when they are not printed to
                    # the screen.
                    totalvalue_len = len(self._trans_hr(ivalue))
                    totalvalue = Pyasciigraph._color_string(
                        self._trans_hr(ivalue), icolor)
                else:
                    totalvalue_len += len("," + self._trans_hr(ivalue))
                    totalvalue += "," + \
                        Pyasciigraph._color_string(
                            self._trans_hr(ivalue),
                            icolor)
                icount += 1
        elif isinstance(value, collections.Iterable):
            max_value = min_neg_value
            color = None
            for (ivalue, icolor) in value:
                if ivalue > max_value:
                    max_value = ivalue
                    color = icolor
            totalvalue_len = len(self._trans_hr(max_value))
            totalvalue = Pyasciigraph._color_string(
                self._trans_hr(max_value), color)

        else:
            totalvalue_len = len(self._trans_hr(value))
            totalvalue = Pyasciigraph._color_string(
                self._trans_hr(value), color)

        number_space = start_info_pos -\
            start_value_pos -\
            totalvalue_len -\
            self.separator_length

        # This must not be negitive, this happens when the string length is
        # larger than the separator length
        if number_space < 0:
            number_space = 0

        return  ' ' * number_space + totalvalue +\
                ' ' * \
            ((start_info_pos - start_value_pos - totalvalue_len)
             - number_space)

    def _sanitize_string(self, string):
        """try to convert strings to UTF-8
        """
        # get the type of a unicode string
        unicode_type = type(Pyasciigraph._u('t'))
        input_type = type(string)
        if input_type is str:
            if sys.version < '3':
                info = unicode(string)
            else:
                info = string
        elif input_type is unicode_type:
            info = string
        elif input_type is int or input_type is float:
            if sys.version < '3':
                info = unicode(string)
            else:
                info = str(string)
        return info

    def _sanitize_value(self, value):
        """try to values to UTF-8
        """
        if isinstance(value, collections.Iterable):
            newcollection = []
            for i in value:
                if len(i) == 1:
                    newcollection.append((i[0], None))
                elif len(i) >= 2:
                    newcollection.append((i[0], i[1]))
            return newcollection
        else:
            return value

    def _sanitize_data(self, data):
        ret = []
        for item in data:
            if (len(item) == 2):
                if isinstance(item[1], collections.Iterable):
                    ret.append(
                        (self._sanitize_string(item[0]),
                         self._sanitize_value(item[1]),
                         None))
                else:
                    ret.append(
                        (self._sanitize_string(item[0]),
                         self._sanitize_value(item[1]),
                         None))
            if (len(item) == 3):
                ret.append(
                    (self._sanitize_string(item[0]),
                     self._sanitize_value(item[1]),
                     item[2]))
        return ret

    def graph(self, label=None, data=[]):
        """function generating the graph

        :param string label: the label of the graph
        :param iterable data: the data (list of tuple (info, value))
                info must be "castable" to a unicode string
                value must be an int or a float
        :rtype: a list of strings (each lines of the graph)

        """
        result = []
        san_data = self._sanitize_data(data)
        all_thre = self._get_thresholds(san_data)

        if not label is None:
            san_label = self._sanitize_string(label)
            label_len = self._len_noansi(san_label)
        else:
            label_len = 0

        real_line_length = max(self.line_length, label_len)

        min_line_length = self.min_graph_length +\
            2 * self.separator_length +\
            all_thre['value_max_length'] +\
            all_thre['info_max_length']

        if min_line_length < real_line_length:
            # calcul of where to start info
            start_info_pos = self.line_length -\
                all_thre['info_max_length']
            # calcul of where to start value
            start_value_pos = start_info_pos -\
                self.separator_length -\
                all_thre['value_max_length']
            # calcul of where to end graph
            graph_length = start_value_pos -\
                self.separator_length
        else:
            # calcul of where to start value
            start_value_pos = self.min_graph_length +\
                self.separator_length
            # calcul of where to start info
            start_info_pos = start_value_pos +\
                all_thre['value_max_length'] +\
                self.separator_length
            # calcul of where to end graph
            graph_length = start_value_pos -\
                self.separator_length
            # calcul of the real line length
            real_line_length = min_line_length

        if not label is None:
            result.append(san_label)
            result.append(Pyasciigraph._u(self.titlebar) * real_line_length)

        for info, value, color in san_data:

            graph_string = self._gen_graph_string(
                value,
                    all_thre['max_pos_value'],
                    all_thre['min_neg_value'],
                    graph_length,
                    start_value_pos,
                    color
            )

            value_string = self._gen_value_string(
                value,
                    all_thre['min_neg_value'],
                    color,
                    start_value_pos,
                    start_info_pos,
            )

            info_string = self._gen_info_string(
                info,
                    start_info_pos,
                    real_line_length
            )
            new_line = graph_string + value_string + info_string
            result.append(new_line)

        return result


from pprint import pprint

# Here we scan methods of the class to recover the public ones
# every public method is a slack command
def _scan_methods(obj, cmd_prefix='!'):
    methods = inspect.getmembers(obj, predicate=inspect.ismethod)
    ret = []
    for m in methods:
        if not re.match(r'^_', m[0]):
            method = getattr(obj, m[0])
            sig = inspect.signature(method)
            ret.append((r"^%s%s " % (cmd_prefix, m[0]), method, sig))
            ret.append((r"^%s%s$" % (cmd_prefix, m[0]), method, sig))
    return ret

class WrongNumberOfArgs(Exception):
    pass


class WrongTypeOfArg(Exception):
    pass

# parse the command arguments compare with the method and cast with the type declare
def _parse_cmd(cmd, sig):
    args = re.split('\W+', cmd)[2:]
    ret = {}
    c = 0
    if len(args) != (len(sig.parameters) - 1):
        raise WrongNumberOfArgs()
    for arg in sig.parameters:
        if arg != 'event':
            try:
                ret[arg] = sig.parameters[arg].annotation(args[c])
            except ValueError:
                raise WrongTypeOfArg("wrong type for arg '%s'" % arg)
            c += 1
    return ret

# small wrapper to add a wraper in order to avoid API saturation
class SlackClientWrapper(SlackClient):

    def __init__(*args, **kargs):
        self.lastapicall = 0 
        self.lock = threading.Lock()
        super().__init__(*args, **kargs)
    
    def api_call(*args, **kargs):
        self.lock.acquire()
        try:
            while int(datetime.datetime.now().strftime("%s")) - self.lastapicall < 2:
                time.sleep(0.5)
            super().api_call(*args, **kargs)
            self.lastapicall = int(datetime.datetime.now().strftime("%s"))
        except Exception as e:
            print(str(e))
        finally:
            self.lock.release()

def main():
    slack_token = os.environ["SLACK_API_TOKEN"]
    slack_client = SlackClient(slack_token)
    module = SeLoger(slack_client)
    methods = _scan_methods(module)

    if slack_client.rtm_connect():
        while True:
            events = slack_client.rtm_read()
            for event in events:
                if (
                    'channel' in event and
                    'text' in event and
                    'user' in event and
                    event.get('type') == 'message'
                ):
                    channel = event['channel']
                    user = event['user']
                    text = event['text']
                    #pprint(event)
                    for m in methods:
                        if re.match(m[0], text.lower()):
                            try:
                                args = _parse_cmd(text, m[2])
                                m[1](**args, event=event)
                            except WrongTypeOfArg as e:
                                #print(e) 
                                msg = 'Wrong Number of arguments\n\n' + m[1].__doc__
                                slack_client.api_call(
                                    'chat.postMessage',
                                    channel=channel,
                                    text=str(e),
                                    username='selogerbot',
                                    as_user=False
                                )
                            except WrongNumberOfArgs as e:
                                #print(e) 
                                msg = 'Wrong Number of arguments\n\n' + m[1].__doc__
                                slack_client.api_call(
                                    'chat.postMessage',
                                    channel=channel,
                                    text=msg,
                                    username='selogerbot',
                                    as_user=False
                                )
                            except:
                                msg = 'Oups, I broke in an unexpected way'
                                slack_client.api_call(
                                    'chat.postMessage',
                                    channel=channel,
                                    text=msg,
                                    username='selogerbot',
                                    as_user=False
                                )
            time.sleep(0.1)
    else:
        print('Connection failed, invalid token?')

main()
