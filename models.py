from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime


db = SQLAlchemy()


class Voluntar(UserMixin, db.Model):
    __tablename__ = 'voluntari'
    id = db.Column(db.Integer, primary_key=True)
    nume = db.Column(db.String(100), nullable=False)
    prenume = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    telefon = db.Column(db.String(20))
    departament = db.Column(db.String(50))
    rol = db.Column(db.String(20), default='voluntar')
    parola = db.Column(db.String(200), nullable=False)
    activ = db.Column(db.Boolean, default=True)
    data_inscriere = db.Column(db.DateTime, default=datetime.utcnow)

    pontaje = db.relationship('Pontaj', backref='voluntar', lazy=True)
    confirmari = db.relationship('Confirmare', backref='voluntar', lazy=True)


class Eveniment(db.Model):
    __tablename__ = 'evenimente'
    id = db.Column(db.Integer, primary_key=True)
    titlu = db.Column(db.String(200), nullable=False)
    adversar = db.Column(db.String(100))
    data = db.Column(db.DateTime, nullable=False)
    ora_convocare = db.Column(db.DateTime)
    locatie = db.Column(db.String(200))
    tip = db.Column(db.String(50))
    descriere = db.Column(db.Text)
    activ = db.Column(db.Boolean, default=True)

    pontaje = db.relationship('Pontaj', backref='eveniment', lazy=True)
    confirmari = db.relationship('Confirmare', backref='eveniment', lazy=True)


class Pontaj(db.Model):
    __tablename__ = 'pontaj'
    id = db.Column(db.Integer, primary_key=True)
    voluntar_id = db.Column(db.Integer, db.ForeignKey('voluntari.id'), nullable=False)
    eveniment_id = db.Column(db.Integer, db.ForeignKey('evenimente.id'), nullable=False)
    status = db.Column(db.String(20), default='absent')
    ora_checkin = db.Column(db.DateTime)
    ora_checkout = db.Column(db.DateTime)
    observatii = db.Column(db.Text)


class Confirmare(db.Model):
    __tablename__ = 'confirmari'
    id = db.Column(db.Integer, primary_key=True)
    voluntar_id = db.Column(db.Integer, db.ForeignKey('voluntari.id'), nullable=False)
    eveniment_id = db.Column(db.Integer, db.ForeignKey('evenimente.id'), nullable=False)
    raspuns = db.Column(db.String(20))
    ora_sosire = db.Column(db.String(50))
    data_raspuns = db.Column(db.DateTime, default=datetime.utcnow)

class Alocare(db.Model):
    __tablename__ = 'alocari'
    id = db.Column(db.Integer, primary_key=True)
    voluntar_id = db.Column(db.Integer, db.ForeignKey('voluntari.id'), nullable=False)
    eveniment_id = db.Column(db.Integer, db.ForeignKey('evenimente.id'), nullable=False)
    departament = db.Column(db.String(50))
    data_alocare = db.Column(db.DateTime, default=datetime.utcnow)

    voluntar = db.relationship('Voluntar', backref='alocari', lazy=True)
    eveniment = db.relationship('Eveniment', backref='alocari', lazy=True)

class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'
    id = db.Column(db.Integer, primary_key=True)
    voluntar_id = db.Column(db.Integer, db.ForeignKey('voluntari.id'), nullable=False)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.Text, nullable=False)
    auth = db.Column(db.Text, nullable=False)
    data_creare = db.Column(db.DateTime, default=datetime.utcnow)

class Departament(db.Model):
    __tablename__ = 'departamente'
    id = db.Column(db.Integer, primary_key=True)
    nume = db.Column(db.String(100), unique=True, nullable=False)
    descriere = db.Column(db.Text)

    teamleaderi = db.relationship('DepartamentTeamleader', backref='departament', lazy=True)


class DepartamentTeamleader(db.Model):
    __tablename__ = 'departament_teamleaderi'
    id = db.Column(db.Integer, primary_key=True)
    departament_id = db.Column(db.Integer, db.ForeignKey('departamente.id'), nullable=False)
    voluntar_id = db.Column(db.Integer, db.ForeignKey('voluntari.id'), nullable=False)
    data_alocare = db.Column(db.DateTime, default=datetime.utcnow)

    voluntar = db.relationship('Voluntar', backref='departament_teamleaderi', lazy=True)    