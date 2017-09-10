#!/usr/bin/python3
# -*- coding: utf-8 -*-
# created by Alwin Ebermann (alwin@alwin.net.au)

import requests
import decimal
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import datetime
import json
from db import Jobs
from db import Base
import telegram

bot = telegram.Bot(token='')


def timetohour(time):
    (h, m) = time.split(':')
    return round(int(h) + int(m) / 60, 3)


def send(chat_id, message):
    try:
        bot.sendMessage(chat_id=chat_id, text=message)
    except Unauthorized:
        session = DBSession()
        job = session.query(Jobs).filter(Jobs.userid == chat_id).first()
        job.userid = 0
        session.commit()
        session.close()
        return True
    except (TimedOut, NetworkError):
        return send(chat_id, message)
    except ChatMigrated as e:
        session = DBSession()
        job = session.query(Jobs).filter(Jobs.userid == chat_id).first()
        job.userid = 0
        session.commit()
        session.close()
        return True


def getconnections(start, dest, date):
    search = requests.post("https://ps.bahn.de/preissuche/preissuche/psc_angebotssuche.post?lang=de&country=DEU")
    soup = BeautifulSoup(search.text, "lxml")
    inp = soup.select("#pscExpires")
    psc = inp[0].attrs["value"]
    d = {'lang': 'de', 'country': 'DEU', 'service': 'pscangebotsuche',
         "data": '{"s":"' + start + '","d":"' + dest + '","dt":"' + date.strftime(
             "%d.%m.%y") + '","t":"0:00","dur":1440,"pscexpires":"' + psc + '","dir":1,"sv":true,"ohneICE":false,"bic":false,"tct":"0","c":"2","travellers":[{"typ":"E","bc":"0","alter":""}]}'}
    results = requests.get("https://ps.bahn.de/preissuche/preissuche/psc_service.go", params=d, allow_redirects=False)
    res = results.json()
    connections = list()

    for i in range(len(res["verbindungen"])):
        # get the price now
        price = 0
        for j in range(len(res["angebote"])):
            if str(i) in res["angebote"][str(j)]["sids"]:
                price = decimal.Decimal(res["angebote"][str(j)]["p"].replace(",", "."))
                break

        connection = {"price": price, "duration": timetohour(res["verbindungen"][str(i)]["dur"]),
                      "start_time": timetohour(res["verbindungen"][str(i)]["trains"][0]["dep"]["t"]),
                      "umsteigen": len(res["verbindungen"][str(i)]["trains"]) - 1,
                      "arrival_time": timetohour(res["verbindungen"][str(i)]["trains"][-1]["dep"]["t"])}
        connections.append(connection)

    cheapco = 0
    seccheap = 0
    for verb in connections:
        if verb["duration"] < 9 and str(verb["price"]) == "47.90":
            seccheap += 1
        #        print(str(verb["start_time"])+"h - "+str(verb["arrival_time"])+"h ("+str(verb["duration"])+"h) Price: "+str(verb["price"])+"€ ("+str(verb["umsteigen"])+")")
        if verb["duration"] < 9 and str(verb["price"]) == "29.90":
            cheapco += 1
    return [cheapco, seccheap]


# jetzt gehts richtig los

# erstmal einen DB-Link aufbauen
engine = create_engine('sqlite:///bahn.sqlite')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)

session = DBSession()
jobs = session.query(Jobs)
for job in jobs:
    # find dates to check
    dates = [job.date, job.date - datetime.timedelta(1), job.date + datetime.timedelta(1),
             job.date - datetime.timedelta(7), job.date + datetime.timedelta(7)]
    # get values out of it and compare directly
    cheapest = json.loads(job.cheapest)
    bez = ["Gewünschter Tag", "Vorheriger Tag", "Nächster Tag", "Vorherige Woche", "Nächste Woche"]
    preise = ["29,90€", "47,90€"]
    seccheapest = json.loads(job.secondcheapest)
    changes = ""
    for i in range(len(dates)):
        vals = getconnections(job.start, job.dest, dates[i])
        if vals[0] != cheapest[i]:
            changes += bez[i] + " " + preise[0] + " Angebote verändert von " + str(cheapest[i]) + " auf " + str(
                vals[0]) + "\n"
            cheapest[i] = vals[0]
            job.cheapest = json.dumps(cheapest)
            session.commit()
        if vals[1] != seccheapest[i]:
            changes += bez[i] + " " + preise[1] + " Angebote verändert von " + str(seccheapest[i]) + " auf " + str(
                vals[1]) + "\n"
            seccheapest[i] = vals[1]
            job.secondcheapest = json.dumps(seccheapest)
            session.commit()

    if changes != "" and job.userid != 0:
        changes = "Änderungen auf der Verbindung von " + job.start_name + " nach " + job.dest_name + " am " + job.date.strftime(
            "%a, %d.%m.%y") + " erkannt: \n" + changes
        send(job.userid, changes)

session.close()
