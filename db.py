#!/usr/bin/python3
# -*- coding: utf-8 -*-
# created by Alwin Ebermann (alwin@alwin.net.au)

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import Integer
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy import create_engine
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Connection(Base):
    __tablename__ = 'connection'
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    start = Column(String(9), nullable=False)
    start_name = Column(String(250), nullable=False)
    dest = Column(String(9), nullable=False)
    dest_name = Column(String(250), nullable=False)
    # Additional parameters for the check
    maxduration = Column(Integer, default=3000)
    maxchanges = Column(Integer, default=10)
    maxprice = Column(Float(asdecimal=True), default=200)
    notifications = Column(Integer, default=2)
    # relation to user
    user_id = Column(Integer, ForeignKey('user.id'))
    user = relationship("User", back_populates="connection")

class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    current_selection = Column(String(255), nullable=True)
    connection = relationship("Connection", back_populates="user")
    counter = Column(Integer, nullable=True)

engine = create_engine('sqlite:///config/bahn.sqlite')
Base.metadata.create_all(engine)
