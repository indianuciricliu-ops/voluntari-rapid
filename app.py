from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from models import db, Voluntar, Eveniment, Alocare
from werkzeug.security import generate_password_hash, check_password_hash
from pywebpush import webpush, WebPushException
from functools import wraps
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
import os
from datetime import datetime

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

@app.route('/')
@login_required
def index():
    from models import Pontaj, Eveniment
    from sqlalchemy import func
    acum = datetime.utcnow()
    total_voluntari = Voluntar.query.filter_by(activ=True).count()
    total_evenimente = Eveniment.query.filter_by(activ=True).count()
    evenimente_viitoare = Eveniment.query.filter(Eveniment.data >= acum, Eveniment.activ == True).order_by(Eveniment.data).limit(3).all()
    total_pontaje = Pontaj.query.count()
    prezente = Pontaj.query.filter_by(status='prezent').count()
    rata_prezenta = round((prezente / total_pontaje * 100)) if total_pontaje > 0 else 0
    dept_stats = db.session.query(Voluntar.departament, func.count(Voluntar.id).label('total')).filter_by(activ=True).group_by(Voluntar.departament).all()
    dept_prezenta = db.session.query(Voluntar.departament, func.count(Pontaj.id).label('prezente')).join(Pontaj, Voluntar.id == Pontaj.voluntar_id).filter(Pontaj.status == 'prezent').group_by(Voluntar.departament).all()
    dept_prez_dict = {d: p for d, p in dept_prezenta}
    top_voluntari = db.session.query(Voluntar, func.count(Pontaj.id).label('prezente')).join(Pontaj, Voluntar.id == Pontaj.voluntar_id).filter(Pontaj.status == 'prezent').group_by(Voluntar.id).order_by(func.count(Pontaj.id).desc()).limit(5).all()
    return render_template('dashboard.html', total_voluntari=total_voluntari, total_evenimente=total_evenimente, evenimente_viitoare=evenimente_viitoare, rata_prezenta=rata_prezenta, prezente=prezente, total_pontaje=total_pontaje, dept_stats=dept_stats, dept_prez_dict=dept_prez_dict, top_voluntari=top_voluntari, acum=acum)

@app.route('/statistici')
@login_required
@admin_or_teamleader_required
def statistici():
    from models import Pontaj
    from sqlalchemy import func, case
    total_voluntari = Voluntar.query.filter_by(activ=True).count()
    total_evenimente = Eveniment.query.filter_by(activ=True).count()
    total_pontaje = Pontaj.query.count()
    total_prezente = Pontaj.query.filter_by(status='prezent').count()
    total_absenti = Pontaj.query.filter_by(status='absent').count()
    rata_globala = round((total_prezente / total_pontaje * 100), 1) if total_pontaje else 0

    voluntari_stats = db.session.query(
        Voluntar.id,
        Voluntar.nume,
        Voluntar.prenume,
        Voluntar.departament,
        Voluntar.rol,
        func.sum(case((Pontaj.status == 'prezent', 1), else_=0)).label('prezente'),
        func.sum(case((Pontaj.status == 'absent', 1), else_=0)).label('absente'),
        func.count(Pontaj.id).label('total')
    ).outerjoin(Pontaj, Voluntar.id == Pontaj.voluntar_id).filter(Voluntar.activ == True).group_by(Voluntar.id).all()

    voluntari_rank = []
    for v in voluntari_stats:
        total = int(v.total or 0)
        prezente = int(v.prezente or 0)
        absente = int(v.absente or 0)
        rata = round((prezente / total * 100), 1) if total else 0
        voluntari_rank.append({
            'id': v.id,
            'nume': v.nume,
            'prenume': v.prenume,
            'departament': v.departament,
            'rol': v.rol,
            'prezente': prezente,
            'absente': absente,
            'total': total,
            'rata': rata
        })

    top_voluntari = sorted(voluntari_rank, key=lambda x: (x['rata'], x['prezente']), reverse=True)[:10]
    cei_mai_multe_absente = sorted(voluntari_rank, key=lambda x: (x['absente'], -x['rata']), reverse=True)[:10]

    evenimente_stats = db.session.query(
        Eveniment.id,
        Eveniment.titlu,
        Eveniment.data,
        func.count(Pontaj.id).label('total_pontaje'),
        func.sum(case((Pontaj.status == 'prezent', 1), else_=0)).label('prezente'),
        func.sum(case((Pontaj.status == 'absent', 1), else_=0)).label('absente')
    ).outerjoin(Pontaj, Eveniment.id == Pontaj.eveniment_id).group_by(Eveniment.id).order_by(Eveniment.data.desc()).all()

    evenimente_rank = []
    for e in evenimente_stats:
        total = int(e.total_pontaje or 0)
        prezente = int(e.prezente or 0)
        absente = int(e.absente or 0)
        rata = round((prezente / total * 100), 1) if total else 0
        evenimente_rank.append({
            'id': e.id,
            'titlu': e.titlu,
            'data': e.data,
            'total': total,
            'prezente': prezente,
            'absente': absente,
            'rata': rata
        })

    top_evenimente = sorted(evenimente_rank, key=lambda x: (x['rata'], x['prezente']), reverse=True)[:10]
    evenimente_cu_cele_mai_multe_absente = sorted(evenimente_rank, key=lambda x: (x['absente'], -x['rata']), reverse=True)[:10]

    departamente_stats = db.session.query(
        Voluntar.departament,
        func.count(Voluntar.id).label('total_voluntari'),
        func.sum(case((Pontaj.status == 'prezent', 1), else_=0)).label('prezente'),
        func.sum(case((Pontaj.status == 'absent', 1), else_=0)).label('absente')
    ).outerjoin(Pontaj, Voluntar.id == Pontaj.voluntar_id).filter(Voluntar.activ == True).group_by(Voluntar.departament).all()

    dept_rows = []
    for d in departamente_stats:
        prez = int(d.prezente or 0)
        absn = int(d.absente or 0)
        tot = int(d.total_voluntari or 0)
        total_p = prez + absn
        rata = round((prez / total_p * 100), 1) if total_p else 0
        dept_rows.append({
            'departament': d.departament or 'Fără departament',
            'voluntari': tot,
            'prezente': prez,
            'absente': absn,
            'rata': rata
        })

    voluntar_id = request.args.get('voluntar_id', type=int)
    selected_voluntar = db.session.get(Voluntar, voluntar_id) if voluntar_id else None
    selected_hist = []
    selected_tot = {'prezente': 0, 'absente': 0, 'total': 0, 'rata': 0}

    if selected_voluntar:
        selected_hist = db.session.query(Pontaj, Eveniment).join(Eveniment, Pontaj.eveniment_id == Eveniment.id).filter(Pontaj.voluntar_id == selected_voluntar.id).order_by(Eveniment.data.desc()).all()
        p = sum(1 for x, _ in selected_hist if x.status == 'prezent')
        a = sum(1 for x, _ in selected_hist if x.status == 'absent')
        t = len(selected_hist)
        selected_tot = {'prezente': p, 'absente': a, 'total': t, 'rata': round((p / t * 100), 1) if t else 0}

    recent_voluntari = Voluntar.query.filter_by(activ=True).order_by(Voluntar.nume, Voluntar.prenume).all()

    return render_template(
        'statistici.html',
        total_voluntari=total_voluntari,
        total_evenimente=total_evenimente,
        total_pontaje=total_pontaje,
        total_prezente=total_prezente,
        total_absenti=total_absenti,
        rata_globala=rata_globala,
        top_voluntari=top_voluntari,
        cei_mai_multe_absente=cei_mai_multe_absente,
        top_evenimente=top_evenimente,
        evenimente_cu_cele_mai_multe_absente=evenimente_cu_cele_mai_multe_absente,
        dept_rows=dept_rows,
        selected_voluntar=selected_voluntar,
        selected_hist=selected_hist,
        selected_tot=selected_tot,
        recent_voluntari=recent_voluntari
    )

@app.route('/alocari')
@login_required
def alocari():
    evenimente = Eveniment.query.order_by(Eveniment.data.desc()).all()
    alocari_per_eveniment = []
    for event in evenimente:
        alocari_event = Alocare.query.filter_by(eveniment_id=event.id).all()
        departamente = {}
        for al in alocari_event:
            dept_name = al.departament or 'Fără departament'
            if dept_name not in departamente:
                departamente[dept_name] = {'teamleader': None, 'voluntari': []}
            if getattr(al, 'este_teamleader', False):
                departamente[dept_name]['teamleader'] = al.voluntar
            else:
                departamente[dept_name]['voluntari'].append(al.voluntar)
        alocari_per_eveniment.append({'event': event, 'departamente': departamente})
    return render_template('alocari.html', alocari_per_eveniment=alocari_per_eveniment)

@app.route('/alocari/<int:event_id>/pdf')
@login_required
def export_alocari_pdf(event_id):
    event = Eveniment.query.get_or_404(event_id)
    alocari_event = Alocare.query.filter_by(eveniment_id=event.id).all()
    departamente = {}
    for al in alocari_event:
        dept_name = al.departament or 'Fără departament'
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
    p.drawString(2 * cm, y, f"Alocări pentru evenimentul: {getattr(event, 'titlu', 'Eveniment')}")
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
        p.drawString(2.5 * cm, y, f"Teamleader: {tl.prenume} {tl.nume}" if tl else "Teamleader: Nedefinit")
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

@app.route('/pontaj/<int:eveniment_id>')
@login_required
@admin_or_teamleader_required
def pontaj(eveniment_id):
    from models import Confirmare, Pontaj
    e = db.session.get(Eveniment, eveniment_id)
    if not e:
        flash('Evenimentul nu a fost gasit.', 'danger')
        return redirect(url_for('evenimente'))

    voluntari_activi = Voluntar.query.filter_by(activ=True).order_by(Voluntar.departament, Voluntar.nume).all()
    pontaje_existente = {p.voluntar_id: p for p in Pontaj.query.filter_by(eveniment_id=eveniment_id).all()}
    pontaje_json = {p.voluntar_id: p.status for p in Pontaj.query.filter_by(eveniment_id=eveniment_id).all()}
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
    voluntar_id = int(request.form['voluntar_id'])
    status = request.form['status']
    from models import Pontaj
    pontaj_ex = Pontaj.query.filter_by(eveniment_id=eveniment_id, voluntar_id=voluntar_id).first()
    if pontaj_ex:
        pontaj_ex.status = status
        if status == 'prezent' and not pontaj_ex.ora_checkin:
            pontaj_ex.ora_checkin = datetime.utcnow()
    else:
        p = Pontaj(voluntar_id=voluntar_id, eveniment_id=eveniment_id, status=status, ora_checkin=datetime.utcnow() if status == 'prezent' else None)
        db.session.add(p)
    db.session.commit()
    return '', 204

@app.route('/pontaj/<int:eveniment_id>/bulk', methods=['POST'])
@login_required
@admin_or_teamleader_required
def pontaj_bulk(eveniment_id):
    from models import Pontaj
    ids_prezenti = request.form.getlist('prezenti')
    for v in Voluntar.query.filter_by(activ=True).all():
        status = 'prezent' if str(v.id) in ids_prezenti else 'absent'
        pontaj_ex = Pontaj.query.filter_by(eveniment_id=eveniment_id, voluntar_id=v.id).first()
        if pontaj_ex:
            pontaj_ex.status = status
        else:
            db.session.add(Pontaj(voluntar_id=v.id, eveniment_id=eveniment_id, status=status, ora_checkin=datetime.utcnow() if status == 'prezent' else None))
    db.session.commit()
    flash('Pontaj salvat cu succes!', 'success')
    return redirect(url_for('eveniment_detalii', id=eveniment_id))

@app.route('/departamente')
@login_required
def departamente_view():
    from models import Departament
    departamente = Departament.query.order_by(Departament.nume).all()
    teamleaders_map = {}
    for d in departamente:
        teamleaders_map[d.id] = [rel.voluntar for rel in d.teamleaderi if rel.voluntar.activ]
    teamleaders_all = Voluntar.query.filter(Voluntar.activ == True, Voluntar.rol.in_(['coordonator', 'Coordonator'])).order_by(Voluntar.nume).all()
    return render_template('departamente.html', departamente=departamente, teamleaders_map=teamleaders_map, teamleaders_all=teamleaders_all)

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
                conn.execute(text("ALTER TABLE voluntari ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT TRUE"))
                conn.execute(text("ALTER TABLE alocari ADD COLUMN IF NOT EXISTS este_teamleader BOOLEAN DEFAULT FALSE"))
                conn.commit()
        else:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE voluntari ADD COLUMN must_change_password BOOLEAN DEFAULT 1"))
                conn.execute(text("ALTER TABLE alocari ADD COLUMN este_teamleader BOOLEAN DEFAULT 0"))
                conn.commit()
    except Exception as e:
        print(f"Migrare Render/local: {e}")

if __name__ == '__main__':
    app.run(debug=True)