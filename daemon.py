#!/usr/bin/python3
# -*- coding: utf-8 -*-
# created by Alwin Ebermann (alwin@alwin.net.au)
import configparser
import copy
import json
from bs4 import BeautifulSoup
from db import Base
from db import Connection
from db import User
from datetime import date
from datetime import datetime
from re import sub
from decimal import Decimal, InvalidOperation
import logging
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import telegram
import requests
from telegram import InlineKeyboardButton
from telegram import InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from telegram.ext import CommandHandler
from telegram.ext import Filters
from telegram.ext import MessageHandler
from telegram.ext import Updater
from telegram.error import ChatMigrated
from telegram.error import NetworkError
from telegram.error import TimedOut
from telegram.error import Unauthorized

config = configparser.ConfigParser()
config.read('config/config.ini')
engine = create_engine('sqlite:///config/bahn.sqlite')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
updater = Updater(token=config['DEFAULT']['BotToken'])
dispatcher = updater.dispatcher
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)

notifications = ["Keine Benachrichtigungen", "Wöchentliche Benachrichtigungen", "Tägliche Benachrichtigungen"]


def timetomin(s):
    (h, m) = s.split(":")
    return int(h) * 60 + int(m)


def reqcons(connection):
    search = requests.post("https://ps.bahn.de/preissuche/preissuche/psc_angebotssuche.post?lang=de&country=DEU")
    soup = BeautifulSoup(search.text, "lxml")
    inp = soup.select("#pscExpires")
    psc = inp[0].attrs["value"]
    d = {'lang': 'de', 'country': 'DEU', 'service': 'pscangebotsuche',
         "data": '{"s":"' + connection.start + '","d":"' + connection.dest + '","dt":"' + connection.date.strftime(
             "%d.%m.%y") + '","t":"0:00","dur":1440,"pscexpires":"' + psc + '","dir":1,"sv":true,"ohneICE":false,"bic":false,"tct":"0","c":"2","travellers":[{"typ":"E","bc":"0","alter":""}]}'}
    results = requests.get("https://ps.bahn.de/preissuche/preissuche/psc_service.go", params=d, allow_redirects=False)
    res = results.json()
    connections = dict()
    if "error" in res:
        return res["error"]["t"]
    for i in range(len(res["verbindungen"])):
        # get the price now
        price = 0
        for j in range(len(res["angebote"])):
            if str(i) in res["angebote"][str(j)]["sids"]:
                price = Decimal(res["angebote"][str(j)]["p"].replace(",", "."))
                break
        changes = len(res["verbindungen"][str(i)]["trains"]) - 1
        con = {"changes": len(res["verbindungen"][str(i)]["trains"]) - 1,
               "duration": timetomin(res["verbindungen"][str(i)]["dur"]), "price": price,
               "start_time": res["verbindungen"][str(i)]["trains"][0]["dep"]["t"],
               "arrival_time": res["verbindungen"][str(i)]["trains"][-1]["dep"]["t"]}
        if con["changes"] <= connection.maxchanges and con["price"] <= connection.maxprice and con[
            "duration"] <= connection.maxduration:
            if con["price"] not in connections:
                connections.update({con["price"]: [con]})
            else:
                connections.update({con["price"]: connections[con["price"]] + [con]})
    return connections


def send_or_edit(bot, update, text, reply_markup=None):
    try:
        message_id = update.callback_query.message.message_id
        chat_id = update.callback_query.message.chat.id
        try:
            bot.editMessageText(text=text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup,
                                parse_mode=telegram.ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Unauthorized:
            session = DBSession()
            user = session.query(User).filter(User.id == chat_id).first()
            session.delete(user)
            session.commit()
            session.close()
        except TimedOut:
            time.sleep(20)
            return send_or_edit(bot, update, text, reply_markup)
        except ChatMigrated as e:
            session = DBSession()
            user = session.query(User).filter(User.id == chat_id).first()
            user.id = e.new_chat_id
            session.commit()
            session.close()
            return True
        except NetworkError:
            return False
    except AttributeError:
        bot.sendMessage(text=text, chat_id=update.message.chat.id, reply_markup=reply_markup,
                        parse_mode=telegram.ParseMode.MARKDOWN, disable_web_page_preview=True)


def findstation(name):
    payload = {"REQ0JourneyStopsS0A": "1", "REQ0JourneyStopsB": 1, "S": name}
    r = requests.get("https://reiseauskunft.bahn.de/bin/ajax-getstop.exe/dn", params=payload)
    try:
        return json.loads(r.text[23:-23])[0]
    except IndexError:
        return False


def CheckUser(bot, update):
    session = DBSession()
    try:
        chat = update.message.chat
        current_selection = "message"
    except AttributeError:
        chat = update.callback_query.message.chat
        current_selection = update.callback_query.data
    entry = session.query(User).filter(User.id == chat.id).first()
    if not entry:
        # user is unknown
        new_user = User(id=chat.id, first_name=chat.first_name, last_name=chat.last_name, username=chat.username,
                        title=chat.title, counter=0, current_selection="0")
        new_usr = copy.deepcopy(new_user)
        session.add(new_user)
        session.commit()
        message = "Mit diesem Bot kannst du die Preisentwicklung von DB Sparpreisen überwachen. Richte gleich eine Verbindung ein."
        bot.sendMessage(chat_id=chat.id, text=message, reply_markup=telegram.ReplyKeyboardRemove())
        session.close()
        return new_usr
    else:
        entry.counter += 1
        ent = copy.deepcopy(entry)
        entry.current_selection = current_selection if not current_selection == "message" else "0"
        session.commit()
        session.close()
        return ent


def ShowHome(bot, update, usr):
    s = DBSession()
    conns = s.query(Connection).filter(Connection.user_id == usr.id, Connection.date >= date.today()).all()
    if len(conns) > 0:
        message = "Folgende Verbindungen werden überwacht:\n"
        button_list = []
        for conn in conns:
            button_list.append([InlineKeyboardButton("🚄 " + conn.start_name + " - " + conn.dest_name,
                                                     callback_data="1$" + str(conn.id))])
        button_list.append([InlineKeyboardButton("➕ Neuen Verbindung erstellen", callback_data="2$-1")])
        send_or_edit(bot, update, message, InlineKeyboardMarkup(button_list))
    else:
        message = "Noch keine Benachrichtigungen erstellt. Leg gleich los:"
        button_list = [[InlineKeyboardButton("➕ Neuen Benachrichtigung erstellen", callback_data="2$-1")]]
        send_or_edit(bot, update, message, InlineKeyboardMarkup(button_list))
    s.close()


def SetStart(bot, update, usr, args):
    if update.callback_query is not None:
        if len(args) == 2:  # first indication that user wants to change start
            send_or_edit(bot, update, "Bitte gib einen Startbahnhof ein:")
    else:  # now process start and change
        station = findstation(update.message.text)
        if not station:
            s = DBSession()
            entry = s.query(User).filter(User.id == usr.id).first()
            entry.current_selection = "2$" + args[1]
            s.commit()
            s.close()
            send_or_edit(bot, update, "Das ist kein Bahnhof. Bitte nochmal versuchen.")
            return False
        if args[1] == "-1":  # create new entry
            s = DBSession()
            conn = Connection(start=station["extId"], start_name=station["value"], user_id=usr.id, date=date.today(),
                              dest=station["extId"], dest_name=station["value"])
            s.add(conn)
            entry = s.query(User).filter(User.id == usr.id).first()
            entry.current_selection = "3$" + str(conn.id)
            s.commit()
            s.close()
            send_or_edit(bot, update, "Wo soll es von " + station["value"] + " hingehen?")
        else:  # update existing
            s = DBSession()
            conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
            if not conn:
                button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
                send_or_edit(bot, update,
                             "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                             InlineKeyboardMarkup(button_list))
            else:
                conn.start = station["extId"]
                conn.start_name = station["value"]
                s.commit()
                button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                                InlineKeyboardButton("🏠 Home", callback_data="0"),
                                InlineKeyboardButton("⛱️ Ziel ändern", callback_data="3$" + str(conn.id))]]
                send_or_edit(bot, update,
                             "Start erfolgreich geändert.",
                             InlineKeyboardMarkup(button_list))
            s.close()


def SetDest(bot, update, usr, args):
    if update.callback_query is not None:
        if len(args) == 2:  # first indication that user wants to change start
            send_or_edit(bot, update, "Bitte gib einen Zielbahnhof ein:")
    else:  # now process start and change
        station = findstation(update.message.text)
        if not station:
            s = DBSession()
            entry = s.query(User).filter(User.id == usr.id).first()
            entry.current_selection = "2$" + args[1]
            s.commit()
            s.close()
            send_or_edit(bot, update, "Das ist kein Bahnhof. Bitte nochmal versuchen.")
            return False

        s = DBSession()
        conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
        if not conn:
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update,
                         "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                         InlineKeyboardMarkup(button_list))
        else:
            conn.dest = station["extId"]
            conn.dest_name = station["value"]
            s.commit()
            button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                            InlineKeyboardButton("🏠 Home", callback_data="0"),
                            InlineKeyboardButton("🗓 Datum ändern", callback_data="4$" + str(conn.id))]]
            send_or_edit(bot, update, "Ziel erfolgreich geändert.", InlineKeyboardMarkup(button_list))
        s.close()


def SetDate(bot, update, usr, args):
    if update.callback_query is not None:
        if len(args) == 2:  # first indication that user wants to change start
            send_or_edit(bot, update, "Bitte gib ein neues Datum im Format TT.MM.JJJJ ein:")
    else:  # now process start and change
        try:
            dat = datetime.strptime(update.message.text, "%d.%m.%Y").date()
            if dat < dat.today():
                raise ValueError
        except ValueError:
            send_or_edit(bot, update,
                         "Das ist kein gültiges Datum oder liegt schon in der Vergangenheit. Das Format muss TT.MM.JJJJ sein.")
            s = DBSession()
            entry = s.query(User).filter(User.id == usr.id).first()
            entry.current_selection = "4$" + args[1]
            s.commit()
            s.close()
            return False
        s = DBSession()
        conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
        if not conn:
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update,
                         "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                         InlineKeyboardMarkup(button_list))
        else:
            conn.date = dat
            s.commit()
            button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                            InlineKeyboardButton("🏠 Home", callback_data="0"),
                            InlineKeyboardButton("💶 Max. Preis ändern", callback_data="5$" + str(conn.id))]]
            send_or_edit(bot, update, "Datum erfolgreich geändert.", InlineKeyboardMarkup(button_list))
        s.close()


def SetPrice(bot, update, usr, args):
    if update.callback_query is not None:
        if len(args) == 2:  # first indication that user wants to change start
            send_or_edit(bot, update, "Bitte gib einen neuen Maximalpreis an.")
    else:  # now process start and change
        price = sub(r'[^0-9.,]+', "", update.message.text)
        price = sub(r',', ".", price)
        try:
            price = Decimal(price).quantize(Decimal('.01'))
        except InvalidOperation:
            send_or_edit(bot, update,
                         "Diese Eingabe konnte nicht in eine Zahl umgewandelt werden.")
            s = DBSession()
            entry = s.query(User).filter(User.id == usr.id).first()
            entry.current_selection = "5$" + args[1]
            s.commit()
            s.close()
            return False

        s = DBSession()
        conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
        if not conn:
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update,
                         "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                         InlineKeyboardMarkup(button_list))
        else:
            conn.maxprice = price
            s.commit()
            button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                            InlineKeyboardButton("🏠 Home", callback_data="0"),
                            InlineKeyboardButton("🕐 Max. Fahrzeit ändern", callback_data="6$" + str(conn.id))]]
            send_or_edit(bot, update, "Maximalpreis erfolgreich geändert.", InlineKeyboardMarkup(button_list))
        s.close()


def SetDuration(bot, update, usr, args):
    if update.callback_query is not None:
        if len(args) == 2:  # first indication that user wants to change start
            send_or_edit(bot, update, "Bitte gib eine neue Maximaldauer in Minuten an.")
    else:  # now process start and change
        duration = sub(r'\D+', "", update.message.text)
        try:
            duration = int(duration)
            if duration < 0:
                raise ValueError
        except ValueError:
            send_or_edit(bot, update,
                         "Diese Eingabe konnte nicht in eine Zahl umgewandelt werden.")
            s = DBSession()
            entry = s.query(User).filter(User.id == usr.id).first()
            entry.current_selection = "6$" + args[1]
            s.commit()
            s.close()
            return False

        s = DBSession()
        conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
        if not conn:
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update,
                         "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                         InlineKeyboardMarkup(button_list))
        else:
            conn.maxduration = duration
            s.commit()
            button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                            InlineKeyboardButton("🏠 Home", callback_data="0"),
                            InlineKeyboardButton("🚏 Max. Umstiege ändern", callback_data="7$" + str(conn.id))]]
            send_or_edit(bot, update, "Maximaldauer erfolgreich geändert.", InlineKeyboardMarkup(button_list))
        s.close()


def SetChanges(bot, update, usr, args):
    if update.callback_query is not None:
        if len(args) == 2:  # first indication that user wants to change start
            send_or_edit(bot, update, "Bitte gib eine neue Maximalanzahl an Umstiegen an.")
    else:  # now process start and change
        changes = sub(r'\D+', "", update.message.text)
        try:
            changes = int(changes)
            if changes < 0:
                raise ValueError
        except ValueError:
            send_or_edit(bot, update, "Diese Eingabe konnte nicht in eine Zahl umgewandelt werden.")
            s = DBSession()
            entry = s.query(User).filter(User.id == usr.id).first()
            entry.current_selection = "7$" + args[1]
            s.commit()
            s.close()
            return False

        s = DBSession()
        conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
        if not conn:
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update,
                         "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                         InlineKeyboardMarkup(button_list))
        else:
            conn.maxchanges = changes
            s.commit()
            button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                            InlineKeyboardButton("🏠 Home", callback_data="0"),
                            InlineKeyboardButton("📯 Ben. ändern", callback_data="8$" + str(conn.id))]]
            send_or_edit(bot, update, "Maximalumstiege erfolgreich geändert.", InlineKeyboardMarkup(button_list))
        s.close()


def SetNotifications(bot, update, usr, args):
    if len(args) == 2:  # list options
        button_list = [[InlineKeyboardButton("Keine Benachrichtigung", callback_data="8$" + args[1] + "$0")],
                       [InlineKeyboardButton("Wöchentliche Benachrichtigung", callback_data="8$" + args[1] + "$1")],
                       [InlineKeyboardButton("Tägliche Benachrichtigung", callback_data="8$" + args[1] + "$2")]]
        send_or_edit(bot, update, "Wie oft möchtest du über diese Verbindung benachrichtigt werden?",
                     InlineKeyboardMarkup(button_list))
    elif len(args) == 3 and int(args[2]) in [0, 1, 2]:
        s = DBSession()
        conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == int(args[1])).first()
        if not conn:
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update,
                         "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                         InlineKeyboardMarkup(button_list))
        else:
            conn.notifications = int(args[2])
            s.commit()
            button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                            InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update, "Benachrichtigungen erfolgreich geändert.", InlineKeyboardMarkup(button_list))
        s.close()


def ShowConnection(bot, update, usr, args):
    s = DBSession()
    conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
    if not conn:
        button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
        send_or_edit(bot, update,
                     "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                     InlineKeyboardMarkup(button_list))
    else:
        message = "*Verbindung: *" + conn.start_name + " - " + conn.dest_name + "\n*Datum: *" + conn.date.strftime(
            "%d.%m.%Y") + "\n*Maximalpreis: *" + str(conn.maxprice.quantize(Decimal('.01'))).replace(".",
                                                                                                     ",") + "€\n*Maximaldauer: *" + str(
            conn.maxduration // 60) + ":" + format(conn.maxduration % 60, '02d') + "h\n*Maximale Umstiege:* " + str(
            conn.maxchanges) + "\n*Benachrichtigungen:* " + notifications[conn.notifications]
        button_list = [[InlineKeyboardButton("🚉 Start ändern", callback_data="2$" + str(conn.id)),
                        InlineKeyboardButton("⛱️ Ziel ändern", callback_data="3$" + str(conn.id))],
                       [InlineKeyboardButton("🗓 Datum ändern", callback_data="4$" + str(conn.id)),
                        InlineKeyboardButton("💶 Maximalpreis ändern", callback_data="5$" + str(conn.id))],
                       [InlineKeyboardButton("🕐 Maximaldauer ändern", callback_data="6$" + str(conn.id)),
                        InlineKeyboardButton("🚏 Maximale Umstiege ändern", callback_data="7$" + str(conn.id))],
                       [InlineKeyboardButton("📯 Benachrichtigungen ändern", callback_data="8$" + str(conn.id)),
                        InlineKeyboardButton("💣 Löschen", callback_data="10$" + str(conn.id))],
                       [InlineKeyboardButton("🏠 Home", callback_data="0"),
                        InlineKeyboardButton("🎇 Jetzt abrufen", callback_data="9$" + str(conn.id))]]
        send_or_edit(bot, update, message, InlineKeyboardMarkup(button_list))
    s.close()


def DeleteConnection(bot, update, usr, args):
    if len(args) == 2:
        button_list = [[InlineKeyboardButton("💣 Wirklich löschen", callback_data="10$" + args[1] + "$1")],
                       [InlineKeyboardButton("🚄 Zurück", callback_data="1$" + args[1])]]
        send_or_edit(bot, update, "Willst du wirklich diese Verbindung löschen?", InlineKeyboardMarkup(button_list))
    elif len(args) == 3 and args[2] == "1":
        s = DBSession()
        conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == args[1]).first()
        if not conn:
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update,
                         "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                         InlineKeyboardMarkup(button_list))
        else:
            message = "Die Verbindung von " + conn.start_name + " nach " + conn.dest_name + " am " + conn.date.strftime(
                "%d.%m.%Y") + " wurde erfolgreich gelöscht."
            s.delete(conn)
            s.commit()
            button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
            send_or_edit(bot, update, message, InlineKeyboardMarkup(button_list))
        s.close()


def RequestConnections(bot, update, usr, args):
    con = args[1] if len(args) > 1 else 0
    s = DBSession()
    conn = s.query(Connection).filter(Connection.user_id == usr.id, Connection.id == con).first()
    if not conn:
        button_list = [[InlineKeyboardButton("🏠 Home", callback_data="0")]]
        send_or_edit(bot, update,
                     "Diese Verbindung kann nicht gefunden werden. Vielleicht liegt sie in der Vergangenheit.",
                     InlineKeyboardMarkup(button_list))
    else:
        # now get all the data
        entries = reqcons(conn)
        message = "Verbindungen von " + conn.start_name + " nach " + conn.dest_name + " am " + conn.date.strftime(
            "%d.%m.%Y") + ":\n"
        if type(entries) is str:
            message += entries
        elif not entries:
            message = "Keine Verbindungen unter diesen Kriterien gefunden."
        else:
            for key, entry in sorted(entries.items()):
                message += "*" + str(key) + "€:*\n"
                for ent in entry:
                    message += ent["start_time"] + " Uhr - " + ent["arrival_time"] + " Uhr (" + str(
                        ent["duration"] // 60) + "h" + format(ent["duration"] % 60, '02d') + "min), " + str(
                        ent["changes"]) + "x umsteigen\n"
        button_list = [[InlineKeyboardButton("🚄 Verbindung", callback_data="1$" + str(conn.id)),
                        InlineKeyboardButton("🏠 Home", callback_data="0")]]
        send_or_edit(bot, update, message, InlineKeyboardMarkup(button_list))
    s.close()


def Gate(bot, update):
    usr = CheckUser(bot, update)
    if not update.callback_query is None:
        args = update.callback_query.data.split("$")
    else:
        args = usr.current_selection.split("$")
    if len(args) > 1:
        if int(args[0]) == 1:  # show connection details
            ShowConnection(bot, update, usr, args)
        elif int(args[0]) == 2:  # create new or change start
            SetStart(bot, update, usr, args)
        elif int(args[0]) == 3:  # change destination
            SetDest(bot, update, usr, args)
        elif int(args[0]) == 4:  # change date
            SetDate(bot, update, usr, args)
        elif int(args[0]) == 5:  # change maxprice
            SetPrice(bot, update, usr, args)
        elif int(args[0]) == 6:  # change maxduration
            SetDuration(bot, update, usr, args)
        elif int(args[0]) == 7:  # change maxchanges
            SetChanges(bot, update, usr, args)
        elif int(args[0]) == 8:  # change notifications
            SetNotifications(bot, update, usr, args)
        elif int(args[0]) == 9:  # show currently available connections
            RequestConnections(bot, update, usr, args)
        elif int(args[0]) == 10:  # Delete
            DeleteConnection(bot, update, usr, args)
        else:
            ShowHome(bot, update, usr)
    else:
        ShowHome(bot, update, usr)


inlinehandler = CallbackQueryHandler(Gate)
dispatcher.add_handler(inlinehandler)

starthandler = CommandHandler('start', Gate)
dispatcher.add_handler(starthandler)

msghandler = MessageHandler(Filters.text, Gate)
dispatcher.add_handler(msghandler)

updater.start_webhook(listen='localhost', port=int(config['DEFAULT']['Port']),
                      webhook_url=config['DEFAULT']['WebHookUrl'])
updater.bot.setWebhook(webhook_url=config['DEFAULT']['WebHookUrl'])
updater.idle()
updater.stop()
