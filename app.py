from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from models import db, Voluntar
from werkzeug.security import generate_password_hash, check_password_hash
from pywebpush import webpush, WebPushException
from functools import wraps
import os

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'rapid1923')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///voluntari.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Trebuie sa te autentifici pentru a accesa aceasta pagina.'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Voluntar, int(user_id))

# ══════════════════════════════════════
# DECORATORI ROLURI
# ══════════════════════════════════════
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            flash('Acces interzis. Doar adminii pot accesa aceasta pagina.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def admin_or_teamleader_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol not in ['admin', 'teamleader']:
            flash('Acces interzis.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

# ══════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════
@app.route('/')
@login_required
def index():
    from models import Pontaj, Eveniment
    from datetime import datetime
    from sqlalchemy import func

    acum = datetime.utcnow()
    total_voluntari = Voluntar.query.filter_by(activ=True).count()
    total_evenimente = Eveniment.query.filter_by(activ=True).count()
    evenimente_viitoare = Eveniment.query.filter(
        Eveniment.data >= acum, Eveniment.activ == True
    ).order_by(Eveniment.data).limit(3).all()

    total_pontaje = Pontaj.query.count()
    prezente = Pontaj.query.filter_by(status='prezent').count()
    rata_prezenta = round((prezente / total_pontaje * 100)) if total_pontaje > 0 else 0

    dept_stats = db.session.query(
        Voluntar.departament,
        func.count(Voluntar.id).label('total')
    ).filter_by(activ=True).group_by(Voluntar.departament).all()

    dept_prezenta = db.session.query(
        Voluntar.departament,
        func.count(Pontaj.id).label('prezente')
    ).join(Pontaj, Voluntar.id == Pontaj.voluntar_id)\
     .filter(Pontaj.status == 'prezent')\
     .group_by(Voluntar.departament).all()
    dept_prez_dict = {d: p for d, p in dept_prezenta}

    top_voluntari = db.session.query(
        Voluntar,
        func.count(Pontaj.id).label('prezente')
    ).join(Pontaj, Voluntar.id == Pontaj.voluntar_id)\
     .filter(Pontaj.status == 'prezent')\
     .group_by(Voluntar.id)\
     .order_by(func.count(Pontaj.id).desc())\
     .limit(5).all()

    return render_template('dashboard.html',
        total_voluntari=total_voluntari,
        total_evenimente=total_evenimente,
        evenimente_viitoare=evenimente_viitoare,
        rata_prezenta=rata_prezenta,
        prezente=prezente,
        total_pontaje=total_pontaje,
        dept_stats=dept_stats,
        dept_prez_dict=dept_prez_dict,
        top_voluntari=top_voluntari,
        acum=acum
    )

# ══════════════════════════════════════
# API / PUSH NOTIFICATIONS
# ══════════════════════════════════════
@app.route('/api/vapid-public-key')
def vapid_public_key():
    return jsonify({'publicKey': os.environ.get('VAPID_PUBLIC_KEY')})

@app.route('/api/subscribe', methods=['POST'])
@login_required
def subscribe():
    from models import PushSubscription
    data = request.get_json()
    sub = PushSubscription.query.filter_by(endpoint=data['endpoint']).first()
    if not sub:
        sub = PushSubscription(
            voluntar_id=current_user.id,
            endpoint=data['endpoint'],
            p256dh=data['keys']['p256dh'],
            auth=data['keys']['auth']
        )
        db.session.add(sub)
        db.session.commit()
    return jsonify({'status': 'ok'})

def trimite_push_reminder_eveniment(eveniment_id):
    """
    Trimite notificare PWA de reminder pentru evenimentul dat
    DOAR către voluntarii activi care NU au nicio confirmare la acest eveniment.
    """
    from models import Eveniment, Confirmare, PushSubscription
    import json

    e = db.session.get(Eveniment, eveniment_id)
    if not e:
        return 0

    confirmari = Confirmare.query.filter_by(eveniment_id=eveniment_id).all()
    votanti_ids = {c.voluntar_id for c in confirmari}

    subs_query = PushSubscription.query.join(
        Voluntar, PushSubscription.voluntar_id == Voluntar.id
    ).filter(
        Voluntar.activ == True
    )

    if votanti_ids:
        subs_query = subs_query.filter(~Voluntar.id.in_(votanti_ids))

    subs = subs_query.all()

    trimise = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                },
                data=json.dumps({
                    "title": "Reminder eveniment 🔴⚪",
                    "body": f"Te rugăm să confirmi dacă vii la: {e.titlu}",
                    "url": f"/evenimente/{e.id}"
                }),
                vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
                vapid_claims={"sub": os.environ.get('VAPID_EMAIL')}
            )
            trimise += 1
        except WebPushException as err:
            app.logger.warning(f"Push reminder error pentru {sub.endpoint}: {err}")
        except Exception as err:
            app.logger.warning(f"Push reminder altă eroare: {err}")

    return trimise

# ══════════════════════════════════════
# AUTH
# ══════════════════════════════════════
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, 'must_change_password', False):
            return redirect(url_for('schimba_parola'))
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        parola = request.form.get('parola')
        voluntar = Voluntar.query.filter_by(email=email).first()

        if voluntar and check_password_hash(voluntar.parola, parola):
            login_user(voluntar)
            flash(f'Bun venit, {voluntar.prenume}!', 'success')

            if getattr(voluntar, 'must_change_password', False):
                return redirect(url_for('schimba_parola'))

            return redirect(url_for('index'))
        else:
            flash('Email sau parola gresite.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Ai fost deconectat.', 'info')
    return redirect(url_for('login'))

@app.route('/schimba-parola', methods=['GET', 'POST'])
@login_required
def schimba_parola():
    if request.method == 'POST':
        parola_noua = (request.form.get('parola_noua') or '').strip()
        confirmare = (request.form.get('confirmare') or '').strip()

        if not parola_noua or not confirmare:
            flash('Completează toate câmpurile.', 'danger')
            return redirect(url_for('schimba_parola'))

        if parola_noua != confirmare:
            flash('Parolele nu coincid.', 'danger')
            return redirect(url_for('schimba_parola'))

        current_user.parola = generate_password_hash(parola_noua)
        current_user.must_change_password = False
        db.session.commit()

        flash('Parola a fost schimbată cu succes.', 'success')
        return redirect(url_for('index'))

    return render_template('schimba_parola.html')

# ══════════════════════════════════════
# VOLUNTARI
# ══════════════════════════════════════
@app.route('/voluntari')
@login_required
@admin_or_teamleader_required
def voluntari():
    cautare = request.args.get('q', '')
    dept = request.args.get('departament', '')
    query = Voluntar.query.filter_by(activ=True)
    if cautare:
        query = query.filter(
            (Voluntar.nume.ilike(f'%{cautare}%')) |
            (Voluntar.prenume.ilike(f'%{cautare}%')) |
            (Voluntar.email.ilike(f'%{cautare}%'))
        )
    if dept:
        query = query.filter_by(departament=dept)
    lista = query.order_by(Voluntar.nume).all()
    departamente = db.session.query(Voluntar.departament).distinct().all()
    departamente = [d[0] for d in departamente if d[0]]
    return render_template('voluntari.html', voluntari=lista,
                           cautare=cautare, dept=dept, departamente=departamente)

@app.route('/voluntari/nou', methods=['GET', 'POST'])
@login_required
@admin_required
def voluntar_nou():
    from models import Departament

    if request.method == 'POST':
        prenume = (request.form.get('prenume') or '').strip()
        nume = (request.form.get('nume') or '').strip()
        email = (request.form.get('email') or '').strip()
        telefon = (request.form.get('telefon') or '').strip()
        departament = (request.form.get('departament') or '').strip()
        rol = (request.form.get('rol') or '').strip()
        parola = (request.form.get('parola') or '').strip()

        if not parola:
            flash('Parola este obligatorie.', 'danger')
            return redirect(url_for('voluntar_nou'))

        v = Voluntar(
            prenume=prenume,
            nume=nume,
            email=email,
            telefon=telefon,
            departament=departament,
            rol=rol,
            activ=True
        )
        v.must_change_password = True
        v.parola = generate_password_hash(parola)

        db.session.add(v)
        db.session.commit()
        flash('Voluntarul a fost creat.', 'success')
        return redirect(url_for('voluntari'))

    departamente = Departament.query.order_by(Departament.nume).all()
    return render_template('voluntar_nou.html', departamente=departamente)

@app.route('/voluntari/<int:id>')
@login_required
@admin_or_teamleader_required
def voluntar_profil(id):
    from models import Pontaj, Eveniment
    v = db.session.get(Voluntar, id)
    if not v:
        flash('Voluntarul nu a fost gasit.', 'danger')
        return redirect(url_for('voluntari'))
    pontaje = Pontaj.query.filter_by(voluntar_id=id).all()
    total = len(pontaje)
    prezent = len([p for p in pontaje if p.status == 'prezent'])
    return render_template('voluntar_profil.html', v=v,
                           pontaje=pontaje, total=total, prezent=prezent)

@app.route('/voluntari/<int:id>/editeaza', methods=['GET', 'POST'])
@login_required
@admin_required
def voluntar_editeaza(id):
    from models import Departament

    v = db.session.get(Voluntar, id)
    if not v:
        flash('Voluntarul nu a fost gasit.', 'danger')
        return redirect(url_for('voluntari'))

    if request.method == 'POST':
        v.prenume = (request.form.get('prenume') or '').strip()
        v.nume = (request.form.get('nume') or '').strip()
        v.email = (request.form.get('email') or '').strip()
        v.telefon = (request.form.get('telefon') or '').strip()
        v.departament = (request.form.get('departament') or '').strip()
        v.rol = (request.form.get('rol') or '').strip()

        parola_noua = (request.form.get('parola') or '').strip()
        confirmare_parola = (request.form.get('confirmare_parola') or '').strip()

        if parola_noua or confirmare_parola:
            if not parola_noua or not confirmare_parola:
                flash('Completează ambele câmpuri de parolă.', 'danger')
                return redirect(url_for('voluntar_editeaza', id=id))

            if parola_noua != confirmare_parola:
                flash('Parolele nu coincid.', 'danger')
                return redirect(url_for('voluntar_editeaza', id=id))

            v.parola = generate_password_hash(parola_noua)
            v.must_change_password = False

        db.session.commit()
        flash('Profilul voluntarului a fost actualizat.', 'success')
        return redirect(url_for('voluntar_profil', id=id))

    departamente = Departament.query.order_by(Departament.nume).all()
    return render_template('voluntar_editeaza.html', v=v, departamente=departamente)

@app.route('/voluntari/<int:id>/dezactiveaza')
@login_required
@admin_required
def voluntar_dezactiveaza(id):
    v = db.session.get(Voluntar, id)
    v.activ = False
    db.session.commit()
    flash(f'{v.prenume} {v.nume} a fost dezactivat.', 'info')
    return redirect(url_for('voluntari'))

# ══════════════════════════════════════
# EVENIMENTE
# ══════════════════════════════════════
from models import Eveniment

@app.route('/evenimente')
@login_required
def evenimente():
    from datetime import datetime
    acum = datetime.utcnow()
    viitoare = Eveniment.query.filter(Eveniment.data >= acum, Eveniment.activ == True)\
                              .order_by(Eveniment.data).all()
    trecute = Eveniment.query.filter(Eveniment.data < acum, Eveniment.activ == True)\
                            .order_by(Eveniment.data.desc()).limit(10).all()
    return render_template('evenimente.html', viitoare=viitoare, trecute=trecute)

@app.route('/evenimente/nou', methods=['GET', 'POST'])
@login_required
@admin_required
def eveniment_nou():
    from datetime import datetime
    if request.method == 'POST':
        data_str = request.form['data']
        conv_str = request.form.get('ora_convocare', '')
        data = datetime.strptime(data_str, '%Y-%m-%dT%H:%M')
        ora_conv = datetime.strptime(conv_str, '%Y-%m-%dT%H:%M') if conv_str else None
        e = Eveniment(
            titlu=request.form['titlu'],
            adversar=request.form.get('adversar', ''),
            data=data,
            ora_convocare=ora_conv,
            locatie=request.form.get('locatie', ''),
            tip=request.form.get('tip', ''),
            descriere=request.form.get('descriere', '')
        )
        db.session.add(e)
        db.session.commit()

        try:
            from models import PushSubscription
            import json
            subscriptions = PushSubscription.query.all()
            for sub in subscriptions:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                    },
                    data=json.dumps({
                        "title": "Eveniment nou! 🔴⚪",
                        "body": f"A fost adaugat: {e.titlu}",
                        "url": "/evenimente"
                    }),
                    vapid_private_key=os.environ.get('VAPID_PRIVATE_KEY'),
                    vapid_claims={"sub": os.environ.get('VAPID_EMAIL')}
                )
        except Exception as err:
            print(f"Push error: {err}")

        flash(f'Evenimentul "{e.titlu}" a fost creat!', 'success')
        return redirect(url_for('evenimente'))
    return render_template('eveniment_nou.html')

@app.route('/evenimente/<int:id>')
@login_required
def eveniment_detalii(id):
    from models import Pontaj, Confirmare, Alocare
    e = db.session.get(Eveniment, id)
    if not e:
        flash('Evenimentul nu a fost gasit.', 'danger')
        return redirect(url_for('evenimente'))

    confirmari = Confirmare.query.filter_by(eveniment_id=id).all()
    disponibili = [c for c in confirmari if c.raspuns == 'vin']
    indisponibili = [c for c in confirmari if c.raspuns == 'nu_vin']
    nesiguri = [c for c in confirmari if c.raspuns == 'poate']

    confirmare_user = Confirmare.query.filter_by(
        eveniment_id=id, voluntar_id=current_user.id
    ).first()

    pontaje = Pontaj.query.filter_by(eveniment_id=id).all()
    prezenti = [p for p in pontaje if p.status == 'prezent']
    toti_voluntarii = Voluntar.query.filter_by(activ=True).all()

    departamente = [d[0] for d in db.session.query(
        Voluntar.departament
    ).distinct().all() if d[0]]

    alocari = Alocare.query.filter_by(eveniment_id=id).all()
    alocari_dict = {a.voluntar_id: a for a in alocari}

    alocare_user = Alocare.query.filter_by(
        eveniment_id=id, voluntar_id=current_user.id
    ).first()

    return render_template(
        'eveniment_detalii.html',
        e=e,
        disponibili=disponibili,
        indisponibili=indisponibili,
        nesiguri=nesiguri,
        confirmare_user=confirmare_user,
        alocare_user=alocare_user,
        pontaje=pontaje,
        prezenti=prezenti,
        toti_voluntarii=toti_voluntarii,
        departamente=departamente,
        alocari_dict=alocari_dict
    )

@app.route('/evenimente/<int:id>/confirma', methods=['POST'])
@login_required
def eveniment_confirma(id):
    from models import Confirmare
    from datetime import datetime
    import traceback

    try:
        raspuns = (request.form.get('raspuns') or '').strip()
        ora_sosire = (request.form.get('ora_sosire') or '').strip() or None

        app.logger.info(f"CONFIRMARE form={dict(request.form)}")
        app.logger.info(f"CONFIRMARE raspuns={raspuns}, ora_sosire={ora_sosire}")

        if raspuns not in ['vin', 'nu_vin', 'poate']:
            flash('Răspuns invalid.', 'danger')
            return redirect(url_for('eveniment_detalii', id=id))

        confirmare = Confirmare.query.filter_by(
            eveniment_id=id, voluntar_id=current_user.id
        ).first()

        if confirmare:
            confirmare.raspuns = raspuns
            confirmare.ora_sosire = ora_sosire
            confirmare.data_raspuns = datetime.utcnow()
        else:
            confirmare = Confirmare(
                voluntar_id=current_user.id,
                eveniment_id=id,
                raspuns=raspuns,
                ora_sosire=ora_sosire
            )
            db.session.add(confirmare)

        db.session.commit()
        flash('Răspunsul tău a fost salvat!', 'success')
        return redirect(url_for('eveniment_detalii', id=id))

    except Exception:
        db.session.rollback()
        app.logger.exception("EROARE LA CONFIRMARE")
        flash('A apărut o eroare la salvarea confirmării.', 'danger')
        return redirect(url_for('eveniment_detalii', id=id))

@app.route('/evenimente/<int:id>/alocare', methods=['POST'])
@login_required
@admin_or_teamleader_required
def eveniment_alocare(id):
    from models import Alocare
    from datetime import datetime

    voluntar_id = int(request.form.get('voluntar_id', 0))
    departament = (request.form.get('departament') or '').strip()

    if not voluntar_id or not departament:
        flash('Selectează un voluntar și un departament.', 'danger')
        return redirect(url_for('eveniment_detalii', id=id))

    alocare = Alocare.query.filter_by(
        eveniment_id=id, voluntar_id=voluntar_id
    ).first()

    if alocare:
        alocare.departament = departament
        alocare.data_alocare = datetime.utcnow()
    else:
        alocare = Alocare(
            voluntar_id=voluntar_id,
            eveniment_id=id,
            departament=departament
        )
        db.session.add(alocare)

    db.session.commit()
    flash('Alocarea a fost salvată.', 'success')
    return redirect(url_for('eveniment_detalii', id=id))

@app.route('/evenimente/<int:id>/editeaza', methods=['GET', 'POST'])
@login_required
@admin_required
def eveniment_editeaza(id):
    from datetime import datetime
    e = db.session.get(Eveniment, id)
    if request.method == 'POST':
        e.titlu = request.form['titlu']
        e.adversar = request.form.get('adversar', '')
        e.data = datetime.strptime(request.form['data'], '%Y-%m-%dT%H:%M')
        conv_str = request.form.get('ora_convocare', '')
        e.ora_convocare = datetime.strptime(conv_str, '%Y-%m-%dT%H:%M') if conv_str else None
        e.locatie = request.form.get('locatie', '')
        e.tip = request.form.get('tip', '')
        e.descriere = request.form.get('descriere', '')
        db.session.commit()
        flash('Eveniment actualizat!', 'success')
        return redirect(url_for('eveniment_detalii', id=id))
    return render_template('eveniment_editeaza.html', e=e)

@app.route('/evenimente/<int:id>/anuleaza')
@login_required
@admin_required
def eveniment_anuleaza(id):
    e = db.session.get(Eveniment, id)
    e.activ = False
    db.session.commit()
    flash(f'Evenimentul "{e.titlu}" a fost anulat.', 'info')
    return redirect(url_for('evenimente'))

@app.route('/evenimente/<int:id>/trimite-reminder', methods=['POST'])
@login_required
@admin_required
def eveniment_trimite_reminder(id):
    numar = trimite_push_reminder_eveniment(id)
    if numar > 0:
        flash(f'Reminder trimis către {numar} voluntari care nu au votat.', 'success')
    else:
        flash('Nu există voluntari fără răspuns pentru acest eveniment sau nu au subscription PWA.', 'info')
    return redirect(url_for('eveniment_detalii', id=id))

# ══════════════════════════════════════
# PONTAJ
# ══════════════════════════════════════
import qrcode
import io
import base64
from models import Pontaj, Confirmare

@app.route('/pontaj/<int:eveniment_id>')
@login_required
@admin_or_teamleader_required
def pontaj(eveniment_id):
    from models import Confirmare
    e = db.session.get(Eveniment, eveniment_id)
    if not e:
        flash('Evenimentul nu a fost gasit.', 'danger')
        return redirect(url_for('evenimente'))

    voluntari_activi = Voluntar.query.filter_by(activ=True).order_by(
        Voluntar.departament, Voluntar.nume
    ).all()

    pontaje_existente = {
        p.voluntar_id: p for p in Pontaj.query.filter_by(eveniment_id=eveniment_id).all()
    }
    pontaje_json = {
        p.voluntar_id: p.status for p in Pontaj.query.filter_by(eveniment_id=eveniment_id).all()
    }

    confirmari = Confirmare.query.filter_by(eveniment_id=eveniment_id).all()
    raspuns_map = {c.voluntar_id: c.raspuns for c in confirmari}

    confirmati = []
    poate = []
    nevotati_sau_nu_vin = []

    for v in voluntari_activi:
        r = raspuns_map.get(v.id)
        if r == 'vin':
            confirmati.append(v)
        elif r == 'poate':
            poate.append(v)
        else:
            nevotati_sau_nu_vin.append(v)

    return render_template(
        'pontaj.html',
        e=e,
        confirmati=confirmati,
        poate=poate,
        nevotati_sau_nu_vin=nevotati_sau_nu_vin,
        pontaje=pontaje_existente,
        pontaje_json=pontaje_json
    )

@app.route('/pontaj/<int:eveniment_id>/marcheaza', methods=['POST'])
@login_required
@admin_or_teamleader_required
def pontaj_marcheaza(eveniment_id):
    from datetime import datetime
    voluntar_id = int(request.form['voluntar_id'])
    status = request.form['status']
    pontaj_ex = Pontaj.query.filter_by(eveniment_id=eveniment_id, voluntar_id=voluntar_id).first()
    if pontaj_ex:
        pontaj_ex.status = status
        if status == 'prezent' and not pontaj_ex.ora_checkin:
            pontaj_ex.ora_checkin = datetime.utcnow()
    else:
        p = Pontaj(
            voluntar_id=voluntar_id,
            eveniment_id=eveniment_id,
            status=status,
            ora_checkin=datetime.utcnow() if status == 'prezent' else None
        )
        db.session.add(p)
    db.session.commit()
    return '', 204

@app.route('/pontaj/<int:eveniment_id>/bulk', methods=['POST'])
@login_required
@admin_or_teamleader_required
def pontaj_bulk(eveniment_id):
    from datetime import datetime
    ids_prezenti = request.form.getlist('prezenti')
    for v in Voluntar.query.filter_by(activ=True).all():
        status = 'prezent' if str(v.id) in ids_prezenti else 'absent'
        pontaj_ex = Pontaj.query.filter_by(eveniment_id=eveniment_id, voluntar_id=v.id).first()
        if pontaj_ex:
            pontaj_ex.status = status
        else:
            p = Pontaj(
                voluntar_id=v.id,
                eveniment_id=eveniment_id,
                status=status,
                ora_checkin=datetime.utcnow() if status == 'prezent' else None
            )
            db.session.add(p)
    db.session.commit()
    flash('Pontaj salvat cu succes!', 'success')
    return redirect(url_for('eveniment_detalii', id=eveniment_id))

# ══════════════════════════════════════
# QR & CHECKIN
# ══════════════════════════════════════
@app.route('/qr/<int:voluntar_id>')
@login_required
@admin_or_teamleader_required
def qr_voluntar(voluntar_id):
    v = db.session.get(Voluntar, voluntar_id)
    url = f'http://localhost:5000/checkin/{voluntar_id}'
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template('qr.html', v=v, img_b64=img_b64, url=url)

@app.route('/checkin/<int:voluntar_id>')
def checkin_qr(voluntar_id):
    from datetime import datetime
    from models import Eveniment
    v = db.session.get(Voluntar, voluntar_id)
    if not v:
        return 'Voluntar negasit', 404
    acum = datetime.utcnow()
    eveniment = Eveniment.query.filter(
        Eveniment.data >= acum,
        Eveniment.activ == True
    ).order_by(Eveniment.data).first()
    if not eveniment:
        return render_template('checkin_result.html', v=v,
                               mesaj='Nu există niciun eveniment activ în acest moment.', ok=False)
    pontaj_ex = Pontaj.query.filter_by(eveniment_id=eveniment.id, voluntar_id=voluntar_id).first()
    if pontaj_ex:
        pontaj_ex.status = 'prezent'
        pontaj_ex.ora_checkin = acum
    else:
        p = Pontaj(voluntar_id=voluntar_id, eveniment_id=eveniment.id,
                   status='prezent', ora_checkin=acum)
        db.session.add(p)
    db.session.commit()
    return render_template('checkin_result.html', v=v, eveniment=eveniment,
                           mesaj=f'Check-in reușit pentru {eveniment.titlu}!', ok=True)

@app.route('/departamente')
@login_required
def departamente_view():
    from models import Departament, DepartamentTeamleader
    from sqlalchemy import or_

    departamente = Departament.query.order_by(Departament.nume).all()

    teamleaders_map = {}
    for d in departamente:
        tls = [rel.voluntar for rel in d.teamleaderi if rel.voluntar.activ]
        teamleaders_map[d.id] = tls

    teamleaders_all = Voluntar.query.filter(
        Voluntar.activ == True,
        Voluntar.rol.in_(['coordonator', 'Coordonator'])
    ).order_by(Voluntar.nume).all()

    return render_template(
        'departamente.html',
        departamente=departamente,
        teamleaders_map=teamleaders_map,
        teamleaders_all=teamleaders_all
    )

@app.route('/departamente/nou', methods=['POST'])
@login_required
@admin_required
def departament_nou():
    from models import Departament

    nume = (request.form.get('nume') or '').strip()
    descriere = (request.form.get('descriere') or '').strip()

    if not nume:
        flash('Numele departamentului este obligatoriu.', 'danger')
        return redirect(url_for('departamente_view'))

    existing = Departament.query.filter_by(nume=nume).first()
    if existing:
        flash('Există deja un departament cu acest nume.', 'danger')
        return redirect(url_for('departamente_view'))

    d = Departament(nume=nume, descriere=descriere)
    db.session.add(d)
    db.session.commit()
    flash('Departament creat.', 'success')
    return redirect(url_for('departamente_view'))

@app.route('/departamente/<int:id>/editeaza', methods=['POST'])
@login_required
@admin_required
def departament_editeaza(id):
    from models import Departament

    d = db.session.get(Departament, id)
    if not d:
        flash('Departamentul nu există.', 'danger')
        return redirect(url_for('departamente_view'))

    nume = (request.form.get('nume') or '').strip()
    descriere = (request.form.get('descriere') or '').strip()

    if not nume:
        flash('Numele departamentului este obligatoriu.', 'danger')
        return redirect(url_for('departamente_view'))

    d.nume = nume
    d.descriere = descriere
    db.session.commit()
    flash('Departament actualizat.', 'success')
    return redirect(url_for('departamente_view'))

@app.route('/departamente/<int:id>/teamleader/adauga', methods=['POST'])
@login_required
@admin_required
def departament_teamleader_adauga(id):
    from models import Departament, DepartamentTeamleader

    voluntar_id = int(request.form.get('voluntar_id', 0))

    if not voluntar_id:
        flash('Selectează un teamleader.', 'danger')
        return redirect(url_for('departamente_view'))

    d = db.session.get(Departament, id)
    if not d:
        flash('Departamentul nu există.', 'danger')
        return redirect(url_for('departamente_view'))

    v = db.session.get(Voluntar, voluntar_id)
    if not v or v.rol not in ['coordonator', 'Coordonator']:
        flash('Voluntarul selectat nu are rol de coordonator.', 'danger')
        return redirect(url_for('departamente_view'))

    existing = DepartamentTeamleader.query.filter_by(
        departament_id=id, voluntar_id=voluntar_id
    ).first()
    if existing:
        flash('Acest teamleader este deja alocat departamentului.', 'info')
        return redirect(url_for('departamente_view'))

    rel = DepartamentTeamleader(departament_id=id, voluntar_id=voluntar_id)
    db.session.add(rel)
    db.session.commit()
    flash('Teamleader adăugat la departament.', 'success')
    return redirect(url_for('departamente_view'))

@app.route('/departamente/<int:id>/teamleader/sterge', methods=['POST'])
@login_required
@admin_required
def departament_teamleader_sterge(id):
    from models import DepartamentTeamleader

    voluntar_id = int(request.form.get('voluntar_id', 0))

    rel = DepartamentTeamleader.query.filter_by(
        departament_id=id, voluntar_id=voluntar_id
    ).first()
    if not rel:
        flash('Această alocare nu există.', 'danger')
        return redirect(url_for('departamente_view'))

    db.session.delete(rel)
    db.session.commit()
    flash('Teamleader eliminat din departament.', 'info')
    return redirect(url_for('departamente_view'))

# ══════════════════════════════════════
# MISC
# ══════════════════════════════════════
@app.route('/debug/reminder/<int:id>')
@login_required
@admin_required
def debug_reminder(id):
    from models import Eveniment, Confirmare, PushSubscription

    e = db.session.get(Eveniment, id)
    if not e:
        return 'Eveniment inexistent', 404

    confirmari = Confirmare.query.filter_by(eveniment_id=id).all()
    votanti_ids = {c.voluntar_id for c in confirmari}

    voluntari_activi = Voluntar.query.filter_by(activ=True).all()

    subs = PushSubscription.query.all()
    subs_map = {}
    for s in subs:
        subs_map.setdefault(s.voluntar_id, 0)
        subs_map[s.voluntar_id] += 1

    lines = [
        f"Eveniment: #{e.id} - {e.titlu}",
        f"Confirmari: {len(confirmari)} | Votanti IDs: {votanti_ids}",
        f"Voluntari activi: {len(voluntari_activi)}",
        f"Subscriptii totale in DB: {len(subs)}",
        "─" * 50
    ]

    for v in voluntari_activi:
        are_confirmare = "✅ votat" if v.id in votanti_ids else "❌ nevotat"
        subs_count = subs_map.get(v.id, 0)
        sub_status = f"📲 {subs_count} sub" if subs_count > 0 else "🔕 fără sub"
        va_primi = "👉 PRIMEȘTE reminder" if (v.id not in votanti_ids and subs_count > 0) else ""
        lines.append(f"#{v.id} {v.prenume} {v.nume} | {are_confirmare} | {sub_status} {va_primi}")

    return "<pre style='font-family:monospace;padding:20px'>" + "\n".join(lines) + "</pre>"

@app.route('/check-subs')
@login_required
def check_subs():
    from models import PushSubscription
    subs = PushSubscription.query.all()
    return f'Subscriptii in DB: {len(subs)}'

@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js'), 200, {
        'Content-Type': 'application/javascript',
        'Service-Worker-Allowed': '/'
    }

from sqlalchemy import text

with app.app_context():
    db.create_all()

    engine = db.engine
    try:
        if engine.url.drivername.startswith('postgres'):
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE confirmari ALTER COLUMN ora_sosire TYPE VARCHAR(50)"))
                conn.execute(text("""
                    ALTER TABLE voluntari
                    ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT TRUE
                """))
                conn.commit()
                print("✅ Migrare Render: ora_sosire extinsa la VARCHAR(50), must_change_password adăugată")
        else:
            print("Migrare Render: nu este PostgreSQL, sar peste ALTER COLUMN.")
            with engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE voluntari
                    ADD COLUMN must_change_password BOOLEAN DEFAULT 1
                """))
                conn.commit()
                print("✅ Migrare local: must_change_password adăugată")
    except Exception as e:
        print(f"Migrare Render/local must_change_password: {e}")

if __name__ == '__main__':
    app.run(debug=True)