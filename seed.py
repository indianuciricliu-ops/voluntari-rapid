from app import app
from models import db, Voluntar, Eveniment, Pontaj, Confirmare
from models import Voluntar, Eveniment, Pontaj, Confirmare
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

with app.app_context():
    # Sterge si recreaza toate tabelele
    db.drop_all()
    db.create_all()
    print("✅ Tabele create!")

    # --- VOLUNTARI ---
    voluntari = [
        Voluntar(nume='Matei', prenume='Cosmin', email='cosmin@rapid.ro',
                 telefon='0721000001', departament='Acces', rol='admin',
                 parola=generate_password_hash('admin123')),
        Voluntar(nume='Ionescu', prenume='Andrei', email='andrei@rapid.ro',
                 telefon='0721000002', departament='Logistica', rol='coordonator',
                 parola=generate_password_hash('coord123')),
        Voluntar(nume='Popescu', prenume='Maria', email='maria@rapid.ro',
                 telefon='0721000003', departament='Media', rol='voluntar',
                 parola=generate_password_hash('vol123')),
        Voluntar(nume='Dumitrescu', prenume='Alexandru', email='alex@rapid.ro',
                 telefon='0721000004', departament='Acces', rol='voluntar',
                 parola=generate_password_hash('vol123')),
        Voluntar(nume='Constantin', prenume='Elena', email='elena@rapid.ro',
                 telefon='0721000005', departament='Tribune', rol='voluntar',
                 parola=generate_password_hash('vol123')),
    ]
    for v in voluntari:
        db.session.add(v)
    db.session.commit()
    print(f"✅ {len(voluntari)} voluntari adaugati!")

    # --- EVENIMENTE ---
    acum = datetime.utcnow()
    evenimente = [
        Eveniment(titlu='Rapid vs FCSB', adversar='FCSB',
                  data=acum + timedelta(days=2),
                  ora_convocare=acum + timedelta(days=2, hours=-3),
                  locatie='Stadion Giulesti', tip='liga1',
                  descriere='Derby-ul Bucurestiului!'),
        Eveniment(titlu='Rapid vs CFR Cluj', adversar='CFR Cluj',
                  data=acum + timedelta(days=7),
                  ora_convocare=acum + timedelta(days=7, hours=-3),
                  locatie='Stadion Giulesti', tip='liga1'),
        Eveniment(titlu='Sedinta coordonatori', adversar=None,
                  data=acum + timedelta(days=4),
                  ora_convocare=acum + timedelta(days=4),
                  locatie='Online', tip='sedinta'),
        Eveniment(titlu='Rapid vs U Cluj', adversar='U Cluj',
                  data=acum - timedelta(days=5),
                  ora_convocare=acum - timedelta(days=5, hours=-3),
                  locatie='Stadion Giulesti', tip='liga1'),
    ]
    for e in evenimente:
        db.session.add(e)
    db.session.commit()
    print(f"✅ {len(evenimente)} evenimente adaugate!")

    # --- PONTAJ pentru meciul trecut ---
    ev_trecut = Eveniment.query.filter_by(titlu='Rapid vs U Cluj').first()
    statusuri = ['prezent', 'prezent', 'prezent', 'intarziat', 'absent']
    for i, v in enumerate(Voluntar.query.all()):
        p = Pontaj(voluntar_id=v.id, eveniment_id=ev_trecut.id,
                   status=statusuri[i])
        db.session.add(p)
    db.session.commit()
    print("✅ Pontaj adaugat pentru meciul trecut!")

    print("\n🎉 Baza de date este gata!")
    print("\nConturi de test:")
    print("  Admin:       cosmin@rapid.ro   / admin123")
    print("  Coordonator: andrei@rapid.ro   / coord123")
    print("  Voluntar:    maria@rapid.ro    / vol123")