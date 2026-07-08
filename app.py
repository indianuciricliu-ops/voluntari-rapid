import secrets

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from models import db, Voluntar, Eveniment, Alocare
from werkzeug.security import generate_password_hash, check_password_hash
from pywebpush import webpush, WebPushException
from functools import wraps
from datetime import datetime, timezone
import math
from zoneinfo import ZoneInfo
TZ = ZoneInfo("Europe/Bucharest")
GIULESTI_LAT = 44.447315
GIULESTI_LNG = 26.045157
GIULESTI_RADIUS_METERS = 250


def distance_meters(lat1, lon1, lat2, lon2):
    r = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def requires_giulesti_location(user):
    rol = (getattr(user, "rol", "") or "").strip().lower()
    return rol in {"voluntar", "teamleader", "team leader"}
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
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

def to_local(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(TZ)
    return dt.astimezone(TZ)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Voluntar, int(user_id))


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DECORATORI ROLURI
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DASHBOARD
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
@app.route('/')
@login_required
def index():
    from models import Pontaj, Eveniment
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from sqlalchemy import func

    acum = datetime.now(ZoneInfo("Europe/Bucharest"))
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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# API / PUSH NOTIFICATIONS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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
                    "title": "Reminder eveniment nou",
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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# AUTH
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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
            flash('Email sau parolă greșite.', 'danger')

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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# VOLUNTARI
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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
        flash('Voluntarul nu a fost găsit.', 'danger')
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
        flash('Voluntarul nu a fost găsit.', 'danger')
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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# EVENIMENTE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


@app.route('/api/scan-prezenta', methods=['POST'])
@login_required
def api_scan_prezenta():
    from models import Pontaj, Eveniment

    data = request.get_json(force=True)
    token = data.get('token')

    eveniment = Eveniment.query.filter_by(qr_token=token, activ=True).first()
    if not eveniment:
        return jsonify({'status': 'error', 'message': 'QR invalid sau eveniment inexistent.'}), 400

    acum = datetime.now(TZ)

    pontaj = Pontaj.query.filter_by(
        eveniment_id=eveniment.id,
        voluntar_id=current_user.id
    ).first()

    if not pontaj:
        pontaj = Pontaj(
            eveniment_id=eveniment.id,
            voluntar_id=current_user.id,
            status='prezent',
            ora_checkin=acum
        )
        db.session.add(pontaj)
        db.session.commit()
        return jsonify({'status': 'ok', 'action': 'checkin', 'message': f'Check-in înregistrat la {acum.strftime("%H:%M")}'})

    if pontaj.ora_checkin and not pontaj.ora_checkout:
        pontaj.ora_checkout = acum
        db.session.commit()
        return jsonify({'status': 'ok', 'action': 'checkout', 'message': f'Check-out înregistrat la {acum.strftime("%H:%M")}'})

    return jsonify({'status': 'info', 'action': 'none', 'message': 'Ai deja check-in și check-out înregistrate pentru acest eveniment.'})

@app.route('/evenimente')
@login_required
def evenimente():
    from datetime import datetime
    acum = datetime.now(ZoneInfo("Europe/Bucharest"))
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
        e.qr_token = secrets.token_urlsafe(16)
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
                        "title": "Eveniment nou!",
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


from sqlalchemy.exc import OperationalError

@app.route('/evenimente/<int:id>')
@login_required
def eveniment_detalii(id):
    try:
        from models import Pontaj, Confirmare, Alocare
        e = db.session.get(Eveniment, id)
        if not e:
            flash('Evenimentul nu a fost gasit.', 'danger')
            return redirect(url_for('evenimente'))

        if not getattr(e, 'qr_token', None):
            import secrets
            e.qr_token = secrets.token_urlsafe(16)
            db.session.commit()

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
    except OperationalError:
        db.session.rollback()
        flash('S-a pierdut conexiunea la baza de date. Reîncearcă.', 'danger')
        return redirect(url_for('evenimente'))


@app.route("/evenimente/<int:id>/qr")
@login_required
def eveniment_qr(id):
    e = db.session.get(Eveniment, id)
    if not e or not e.qr_token:
        flash("Eveniment invalid.", "danger")
        return redirect(url_for("evenimente"))

    import qrcode
    import io
    from flask import send_file

    img = qrcode.make(e.qr_token)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

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
            from datetime import datetime
            from zoneinfo import ZoneInfo

            confirmare.raspuns = raspuns
            confirmare.ora_sosire = ora_sosire
            confirmare.data_raspuns = datetime.now(ZoneInfo("Europe/Bucharest"))
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

    este_teamleader = request.form.get('este_teamleader') == 'on'

    if alocare:
        alocare.departament = departament
        alocare.este_teamleader = este_teamleader
        alocare.data_alocare = datetime.now(ZoneInfo("Europe/Bucharest"))
    else:
        alocare = Alocare(
            voluntar_id=voluntar_id,
            eveniment_id=id,
            departament=departament,
            este_teamleader=este_teamleader
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


@app.route('/alocari')
@login_required
def alocari():
    evenimente = Eveniment.query.order_by(Eveniment.data.desc()).all()
    alocari_per_eveniment = []

    for event in evenimente:
        alocari_event = Alocare.query.filter_by(eveniment_id=event.id).all()
        departamente = {}

        for al in alocari_event:
            dept_name = al.departament or 'FÄƒrÄƒ departament'
            if dept_name not in departamente:
                departamente[dept_name] = {
                    'teamleader': None,
                    'voluntari': []
                }

            if getattr(al, 'este_teamleader', False):
                departamente[dept_name]['teamleader'] = al.voluntar
            else:
                departamente[dept_name]['voluntari'].append(al.voluntar)

        alocari_per_eveniment.append({
            'event': event,
            'departamente': departamente
        })

    return render_template('alocari.html', alocari_per_eveniment=alocari_per_eveniment)


@app.route('/alocari/<int:event_id>/pdf')
@login_required
def export_alocari_pdf(event_id):
    event = Eveniment.query.get_or_404(event_id)
    alocari_event = Alocare.query.filter_by(eveniment_id=event.id).all()

    departamente = {}
    for al in alocari_event:
        dept_name = al.departament or 'FÄƒrÄƒ departament'
        if dept_name not in departamente:
            departamente[dept_name] = {'teamleader': None, 'voluntari': []}

        if getattr(al, 'este_teamleader', False):
            departamente[dept_name]['teamleader'] = al.voluntar
        else:
            departamente[dept_name]['voluntari'].append(al.voluntar)

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 2 * cm

    p.setFont("Helvetica-Bold", 14)
    p.drawString(2 * cm, y, f"AlocÄƒri pentru evenimentul: {getattr(event, 'titlu', 'Eveniment')}")
    y -= 1 * cm

    p.setFont("Helvetica", 10)
    if getattr(event, 'data', None):
        try:
            data_text = event.data.strftime('%d.%m.%Y %H:%M')
        except Exception:
            data_text = str(event.data)
        p.drawString(2 * cm, y, f"Data: {data_text}")
        y -= 1 * cm

    for dept_name, dept in departamente.items():
        if y < 4 * cm:
            p.showPage()
            y = height - 2 * cm
            p.setFont("Helvetica", 10)

        p.setFont("Helvetica-Bold", 12)
        p.drawString(2 * cm, y, f"Departament: {dept_name}")
        y -= 0.8 * cm

        p.setFont("Helvetica", 10)
        tl = dept['teamleader']
        if tl:
            p.drawString(2.5 * cm, y, f"Teamleader: {tl.prenume} {tl.nume}")
        else:
            p.drawString(2.5 * cm, y, "Teamleader: Nedefinit")
        y -= 0.7 * cm

        p.drawString(2.5 * cm, y, "Voluntari:")
        y -= 0.6 * cm

        if dept['voluntari']:
            for v in dept['voluntari']:
                if y < 3 * cm:
                    p.showPage()
                    y = height - 2 * cm
                    p.setFont("Helvetica", 10)
                p.drawString(3 * cm, y, f"- {v.prenume} {v.nume}")
                y -= 0.6 * cm
        else:
            p.drawString(3 * cm, y, "Niciun voluntar alocat.")
            y -= 0.6 * cm

        y -= 0.4 * cm

    p.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"alocari_{event.id}.pdf",
        mimetype='application/pdf'
    )

@app.route("/statistici")
@login_required
@admin_or_teamleader_required
def statistici():
    from models import Pontaj, Confirmare, Alocare
    from sqlalchemy import func, case

    def format_duration(total_minutes):
        if total_minutes is None:
            return "-"
        total_minutes = int(total_minutes)
        ore = total_minutes // 60
        minute = total_minutes % 60
        if ore and minute:
            return f"{ore}h {minute}m"
        if ore:
            return f"{ore}h"
        return f"{minute}m"

    total_voluntari = Voluntar.query.filter_by(activ=True).count()
    total_evenimente = Eveniment.query.filter_by(activ=True).count()
    total_prezente = Pontaj.query.filter_by(status="prezent").count()
    total_absenti = Pontaj.query.filter_by(status="absent").count()
    total_pontaje = Pontaj.query.count()
    rata_globala = round(total_prezente / total_pontaje * 100, 1) if total_pontaje else 0

    voluntari_stats = (
        db.session.query(
            Voluntar.id,
            Voluntar.nume,
            Voluntar.prenume,
            Voluntar.departament,
            Voluntar.rol,
            func.sum(case((Pontaj.status == "prezent", 1), else_=0)).label("prezente"),
            func.sum(case((Pontaj.status == "absent", 1), else_=0)).label("absente"),
            func.sum(case((Pontaj.status == "intarziat", 1), else_=0)).label("intarziate"),
            func.count(Pontaj.id).label("total"),
        )
        .outerjoin(Pontaj, Voluntar.id == Pontaj.voluntar_id)
        .filter(Voluntar.activ == True)
        .group_by(Voluntar.id)
        .all()
    )

    voluntari_rank = []
    for v in voluntari_stats:
        total = int(v.total or 0)
        prezente = int(v.prezente or 0)
        absente = int(v.absente or 0)
        intarziate = int(v.intarziate or 0)
        rata = round(prezente / total * 100, 1) if total else 0

        voluntari_rank.append({
            "id": v.id,
            "nume": v.nume,
            "prenume": v.prenume,
            "departament": v.departament,
            "rol": v.rol,
            "prezente": prezente,
            "absente": absente,
            "intarziate": intarziate,
            "total": total,
            "rata": rata
        })

    top_voluntari = sorted(
        voluntari_rank,
        key=lambda x: (x["rata"], x["prezente"]),
        reverse=True
    )[:10]

    cei_mai_multe_absente = sorted(
        voluntari_rank,
        key=lambda x: (x["absente"], -x["rata"]),
        reverse=True
    )[:10]

    evenimente_stats = (
        db.session.query(
            Eveniment.id,
            Eveniment.titlu,
            Eveniment.data,
            func.count(Pontaj.id).label("total_pontaje"),
            func.sum(case((Pontaj.status == "prezent", 1), else_=0)).label("prezente"),
            func.sum(case((Pontaj.status == "absent", 1), else_=0)).label("absente"),
            func.sum(case((Pontaj.status == "intarziat", 1), else_=0)).label("intarziate"),
        )
        .outerjoin(Pontaj, Eveniment.id == Pontaj.eveniment_id)
        .group_by(Eveniment.id)
        .order_by(Eveniment.data.desc())
        .all()
    )

    evenimente_rank = []
    for e in evenimente_stats:
        total = int(e.total_pontaje or 0)
        prezente = int(e.prezente or 0)
        absente = int(e.absente or 0)
        intarziate = int(e.intarziate or 0)
        rata = round(prezente / total * 100, 1) if total else 0

        evenimente_rank.append({
            "id": e.id,
            "titlu": e.titlu,
            "data": e.data,
            "total": total,
            "prezente": prezente,
            "absente": absente,
            "intarziate": intarziate,
            "rata": rata
        })

    top_evenimente = sorted(
        evenimente_rank,
        key=lambda x: (x["rata"], x["prezente"]),
        reverse=True
    )[:10]

    evenimente_cu_cele_mai_multe_absente = sorted(
        evenimente_rank,
        key=lambda x: (x["absente"], -x["rata"]),
        reverse=True
    )[:10]

    departamente_stats = (
        db.session.query(
            Voluntar.departament,
            func.count(Voluntar.id).label("total_voluntari"),
            func.sum(case((Pontaj.status == "prezent", 1), else_=0)).label("prezente"),
            func.sum(case((Pontaj.status == "absent", 1), else_=0)).label("absente"),
            func.sum(case((Pontaj.status == "intarziat", 1), else_=0)).label("intarziate"),
        )
        .outerjoin(Pontaj, Voluntar.id == Pontaj.voluntar_id)
        .filter(Voluntar.activ == True)
        .group_by(Voluntar.departament)
        .all()
    )

    dept_rows = []
    for d in departamente_stats:
        prez = int(d.prezente or 0)
        absn = int(d.absente or 0)
        intz = int(d.intarziate or 0)
        tot = int(d.total_voluntari or 0)
        total_status = prez + absn + intz
        rata = round(prez / total_status * 100, 1) if total_status else 0

        dept_rows.append({
            "departament": d.departament or "Fără departament",
            "voluntari": tot,
            "prezente": prez,
            "absente": absn,
            "intarziate": intz,
            "rata": rata
        })

    voluntar_id = request.args.get("voluntar_id", type=int)
    eveniment_id = request.args.get("eveniment_id", type=int)

    selected_voluntar = db.session.get(Voluntar, voluntar_id) if voluntar_id else None
    selected_eveniment = db.session.get(Eveniment, eveniment_id) if eveniment_id else None

    selected_hist = []
    selected_tot = {
        "prezente": 0,
        "absente": 0,
        "intarziate": 0,
        "total": 0,
        "rata": 0,
        "total_minute": 0,
        "total_ore_formatat": "0m",
        "media_minute": 0,
        "media_ore_formatata": "0m",
    }

    if selected_voluntar:
        rows = (
            db.session.query(Pontaj, Eveniment)
            .join(Eveniment, Pontaj.eveniment_id == Eveniment.id)
            .filter(Pontaj.voluntar_id == selected_voluntar.id)
            .order_by(Eveniment.data.desc())
            .all()
        )

        total_minute = 0
        nr_cu_durata = 0

        for p, ev in rows:
            p.ora_checkin = to_local(p.ora_checkin)
            p.ora_checkout = to_local(p.ora_checkout)

            durata_min = None
            durata_formatata = "-"
            if p.ora_checkin and p.ora_checkout and p.ora_checkout >= p.ora_checkin:
                durata_min = int((p.ora_checkout - p.ora_checkin).total_seconds() // 60)
                durata_formatata = format_duration(durata_min)
                total_minute += durata_min
                nr_cu_durata += 1

            selected_hist.append({
                "pontaj": p,
                "eveniment": ev,
                "durata_min": durata_min,
                "durata_formatata": durata_formatata
            })

        prez = sum(1 for row in selected_hist if row["pontaj"].status == "prezent")
        absn = sum(1 for row in selected_hist if row["pontaj"].status == "absent")
        intz = sum(1 for row in selected_hist if row["pontaj"].status == "intarziat")
        total = len(selected_hist)
        rata = round(prez / total * 100, 1) if total else 0
        media_minute = round(total_minute / nr_cu_durata) if nr_cu_durata else 0

        selected_tot = {
            "prezente": prez,
            "absente": absn,
            "intarziate": intz,
            "total": total,
            "rata": rata,
            "total_minute": total_minute,
            "total_ore_formatat": format_duration(total_minute),
            "media_minute": media_minute,
            "media_ore_formatata": format_duration(media_minute),
        }

    selected_eveniment_stats = None
    selected_eveniment_hist = []

    if selected_eveniment:
        confirmari = Confirmare.query.filter_by(eveniment_id=selected_eveniment.id).all()
        pontaje = Pontaj.query.filter_by(eveniment_id=selected_eveniment.id).all()
        alocari = Alocare.query.filter_by(eveniment_id=selected_eveniment.id).all()

        pontaj_map = {p.voluntar_id: p for p in pontaje}
        confirmare_map = {c.voluntar_id: c for c in confirmari}
        alocare_map = {a.voluntar_id: a for a in alocari}

        voluntari_event_ids = set()
        voluntari_event_ids.update(p.voluntar_id for p in pontaje)
        voluntari_event_ids.update(c.voluntar_id for c in confirmari)
        voluntari_event_ids.update(a.voluntar_id for a in alocari)

        if voluntari_event_ids:
            voluntari_event = (
                Voluntar.query
                .filter(Voluntar.id.in_(voluntari_event_ids))
                .order_by(Voluntar.departament, Voluntar.nume, Voluntar.prenume)
                .all()
            )
        else:
            voluntari_event = []

        total_minute_eveniment = 0
        cu_durata = 0
        prezente = 0
        absente = 0
        intarziati = 0
        votati = 0
        vin = 0
        poate = 0
        nu_vin = 0

        for v in voluntari_event:
            pontaj = pontaj_map.get(v.id)
            confirmare = confirmare_map.get(v.id)
            alocare = alocare_map.get(v.id)

            durata_min = None
            durata_formatata = "-"
            checkin_local = None
            checkout_local = None
            status_pontaj = "-"

            if pontaj:
                pontaj.ora_checkin = to_local(pontaj.ora_checkin)
                pontaj.ora_checkout = to_local(pontaj.ora_checkout)
                checkin_local = pontaj.ora_checkin
                checkout_local = pontaj.ora_checkout
                status_pontaj = pontaj.status or "-"

                if pontaj.status == "prezent":
                    prezente += 1
                elif pontaj.status == "absent":
                    absente += 1
                elif pontaj.status == "intarziat":
                    intarziati += 1

                if checkin_local and checkout_local and checkout_local >= checkin_local:
                    durata_min = int((checkout_local - checkin_local).total_seconds() // 60)
                    durata_formatata = format_duration(durata_min)
                    total_minute_eveniment += durata_min
                    cu_durata += 1

            raspuns_confirmare = "-"
            if confirmare:
                votati += 1
                raspuns_confirmare = confirmare.raspuns or "-"
                if confirmare.raspuns == "vin":
                    vin += 1
                elif confirmare.raspuns == "poate":
                    poate += 1
                elif confirmare.raspuns == "nuvin":
                    nu_vin += 1

            selected_eveniment_hist.append({
                "voluntar": v,
                "confirmare": confirmare,
                "alocare": alocare,
                "pontaj": pontaj,
                "departament": (alocare.departament if alocare and alocare.departament else v.departament),
                "status_confirmare": raspuns_confirmare,
                "status_pontaj": status_pontaj,
                "checkin": checkin_local,
                "checkout": checkout_local,
                "durata_min": durata_min,
                "durata_formatata": durata_formatata
            })

        total_alocati = len(alocari)
        total_votati = votati
        total_nevotati = max(total_alocati - total_votati, 0)
        total_pontati = len(pontaje)
        rata_prezenta = round(prezente / total_pontati * 100, 1) if total_pontati else 0

        selected_eveniment_stats = {
            "alocati": total_alocati,
            "votati": total_votati,
            "nevotati": total_nevotati,
            "vin": vin,
            "poate": poate,
            "nu_vin": nu_vin,
            "prezenti": prezente,
            "absenti": absente,
            "intarziati": intarziati,
            "pontati": total_pontati,
            "rata": rata_prezenta,
            "total_minute": total_minute_eveniment,
            "total_ore_formatat": format_duration(total_minute_eveniment),
            "media_ore_formatata": format_duration(round(total_minute_eveniment / cu_durata)) if cu_durata else "0m",
            "cu_durata": cu_durata
        }

    recent_voluntari = Voluntar.query.filter_by(activ=True).order_by(Voluntar.nume, Voluntar.prenume).all()
    recent_evenimente = Eveniment.query.filter_by(activ=True).order_by(Eveniment.data.desc()).all()

    return render_template(
        "statistici.html",
        total_voluntari=total_voluntari,
        total_evenimente=total_evenimente,
        total_prezente=total_prezente,
        total_absenti=total_absenti,
        total_pontaje=total_pontaje,
        rata_globala=rata_globala,
        top_voluntari=top_voluntari,
        cei_mai_multe_absente=cei_mai_multe_absente,
        top_evenimente=top_evenimente,
        evenimente_cu_cele_mai_multe_absente=evenimente_cu_cele_mai_multe_absente,
        dept_rows=dept_rows,
        selected_voluntar=selected_voluntar,
        selected_hist=selected_hist,
        selected_tot=selected_tot,
        recent_voluntari=recent_voluntari,
        selected_eveniment=selected_eveniment,
        selected_eveniment_stats=selected_eveniment_stats,
        selected_eveniment_hist=selected_eveniment_hist,
        recent_evenimente=recent_evenimente
    )

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PONTAJ
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
import qrcode
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
    for p in pontaje_existente.values():
        p.ora_checkin = to_local(p.ora_checkin)
        p.ora_checkout = to_local(p.ora_checkout)

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
            from zoneinfo import ZoneInfo
            pontaj_ex.ora_checkin = datetime.now(ZoneInfo("Europe/Bucharest"))
    else:
        from zoneinfo import ZoneInfo
        p = Pontaj(
            voluntar_id=voluntar_id,
            eveniment_id=eveniment_id,
            status=status,
            ora_checkin=datetime.now(ZoneInfo("Europe/Bucharest")) if status == 'prezent' else None
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
                ora_checkin=datetime.now(ZoneInfo("Europe/Bucharest")) if status == 'prezent' else None
            )
            db.session.add(p)
    db.session.commit()
    flash('Pontaj salvat cu succes!', 'success')
    return redirect(url_for('eveniment_detalii', id=eveniment_id))


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# QR & CHECKIN
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
import qrcode
import base64
from models import Pontaj, Confirmare

@app.route('/qr/<int:voluntar_id>')
@login_required
@admin_or_teamleader_required
def qr_voluntar(voluntar_id):
    v = db.session.get(Voluntar, voluntar_id)
    if not v:
        flash('Voluntarul nu a fost găsit.', 'danger')
        return redirect(url_for('voluntari'))

    qr_text = f"VOLUNTAR:{v.id}"
    img = qrcode.make(qr_text)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    return render_template('qr.html', v=v, img_b64=img_b64, qr_text=qr_text)


@app.route('/scan/<int:event_id>')
@login_required
def scan_qr(event_id):
    e = db.session.get(Eveniment, event_id)
    if not e:
        flash('Evenimentul nu a fost găsit.', 'danger')
        return redirect(url_for('evenimente'))

    return render_template('scan.html', e=e, event_id=event_id)


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


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MISC
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
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
        "â”€" * 50
    ]

    for v in voluntari_activi:
        are_confirmare = "âœ… votat" if v.id in votanti_ids else "âŒ nevotat"
        subs_count = subs_map.get(v.id, 0)
        sub_status = f"ðŸ“² {subs_count} sub" if subs_count > 0 else "ðŸ”• fÄƒrÄƒ sub"
        va_primi = "ðŸ‘‰ PRIMEÈ˜TE reminder" if (v.id not in votanti_ids and subs_count > 0) else ""
        lines.append(f"#{v.id} {v.prenume} {v.nume} | {are_confirmare} | {sub_status} {va_primi}")

    return "<pre style='font-family:monospace;padding:20px'>" + "\n".join(lines) + "</pre>"

from werkzeug.exceptions import HTTPException

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    if request.path.startswith('/api/'):
        return jsonify({
            'success': False,
            'message': e.description,
            'error': e.name
        }), e.code
    return e

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
                conn.execute(text("""
                    ALTER TABLE alocari
                    ADD COLUMN IF NOT EXISTS este_teamleader BOOLEAN DEFAULT FALSE
                """))
                conn.execute(text("""
                    ALTER TABLE evenimente
                    ADD COLUMN IF NOT EXISTS qr_token VARCHAR(64)
                """))
                conn.commit()
                print("✅ Migrare Render: ora_sosire extinsa la VARCHAR(50), must_change_password, este_teamleader și qr_token adăugate")
        else:
            print("Migrare Render: nu este PostgreSQL, sar peste ALTER COLUMN.")
            with engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE voluntari
                    ADD COLUMN must_change_password BOOLEAN DEFAULT 1
                """))
                conn.execute(text("""
                    ALTER TABLE alocari
                    ADD COLUMN este_teamleader BOOLEAN DEFAULT 0
                """))
                conn.execute(text("""
                    ALTER TABLE evenimente
                    ADD COLUMN qr_token VARCHAR(64)
                """))
                conn.commit()
                print("✅ Migrare local: must_change_password, este_teamleader și qr_token adăugate")
    except Exception as e:
        print(f"Migrare Render/local: {e}")


if __name__ == '__main__':
    app.run(debug=True)