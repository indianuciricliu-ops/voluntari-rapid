from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from models import db, Voluntar
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

    # Statistici pe departamente
    dept_stats = db.session.query(
        Voluntar.departament,
        func.count(Voluntar.id).label('total')
    ).filter_by(activ=True).group_by(Voluntar.departament).all()

    # Prezenta pe departamente
    dept_prezenta = db.session.query(
        Voluntar.departament,
        func.count(Pontaj.id).label('prezente')
    ).join(Pontaj, Voluntar.id == Pontaj.voluntar_id)\
     .filter(Pontaj.status == 'prezent')\
     .group_by(Voluntar.departament).all()
    dept_prez_dict = {d: p for d, p in dept_prezenta}

    # Top 5 voluntari
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        parola = request.form.get('parola')
        voluntar = Voluntar.query.filter_by(email=email).first()
        from werkzeug.security import check_password_hash
        if voluntar and check_password_hash(voluntar.parola, parola):
            login_user(voluntar)
            flash(f'Bun venit, {voluntar.prenume}!', 'success')
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

@app.route('/voluntari')
@login_required
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
def voluntar_nou():
    if request.method == 'POST':
        from werkzeug.security import generate_password_hash
        v = Voluntar(
            nume=request.form['nume'],
            prenume=request.form['prenume'],
            email=request.form['email'],
            telefon=request.form.get('telefon', ''),
            departament=request.form.get('departament', ''),
            rol=request.form.get('rol', 'voluntar'),
            parola=generate_password_hash(request.form['parola'])
        )
        db.session.add(v)
        db.session.commit()
        flash(f'Voluntarul {v.prenume} {v.nume} a fost adaugat!', 'success')
        return redirect(url_for('voluntari'))
    return render_template('voluntar_nou.html')

@app.route('/voluntari/<int:id>')
@login_required
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
def voluntar_editeaza(id):
    v = db.session.get(Voluntar, id)
    if request.method == 'POST':
        v.nume = request.form['nume']
        v.prenume = request.form['prenume']
        v.email = request.form['email']
        v.telefon = request.form.get('telefon', '')
        v.departament = request.form.get('departament', '')
        v.rol = request.form.get('rol', 'voluntar')
        db.session.commit()
        flash('Date actualizate cu succes!', 'success')
        return redirect(url_for('voluntar_profil', id=id))
    return render_template('voluntar_editeaza.html', v=v)

@app.route('/voluntari/<int:id>/dezactiveaza')
@login_required
def voluntar_dezactiveaza(id):
    v = db.session.get(Voluntar, id)
    v.activ = False
    db.session.commit()
    flash(f'{v.prenume} {v.nume} a fost dezactivat.', 'info')
    return redirect(url_for('voluntari'))

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
        flash(f'Evenimentul "{e.titlu}" a fost creat!', 'success')
        return redirect(url_for('evenimente'))
    return render_template('eveniment_nou.html')

@app.route('/evenimente/<int:id>')
@login_required
def eveniment_detalii(id):
    from models import Pontaj, Confirmare
    e = db.session.get(Eveniment, id)
    if not e:
        flash('Evenimentul nu a fost gasit.', 'danger')
        return redirect(url_for('evenimente'))
    confirmari = Confirmare.query.filter_by(eveniment_id=id).all()
    disponibili = [c for c in confirmari if c.raspuns == 'disponibil']
    indisponibili = [c for c in confirmari if c.raspuns == 'indisponibil']
    pontaje = Pontaj.query.filter_by(eveniment_id=id).all()
    prezenti = [p for p in pontaje if p.status == 'prezent']
    toti_voluntarii = Voluntar.query.filter_by(activ=True).all()
    return render_template('eveniment_detalii.html', e=e,
                           disponibili=disponibili, indisponibili=indisponibili,
                           pontaje=pontaje, prezenti=prezenti,
                           toti_voluntarii=toti_voluntarii)

@app.route('/evenimente/<int:id>/editeaza', methods=['GET', 'POST'])
@login_required
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
def eveniment_anuleaza(id):
    e = db.session.get(Eveniment, id)
    e.activ = False
    db.session.commit()
    flash(f'Evenimentul "{e.titlu}" a fost anulat.', 'info')
    return redirect(url_for('evenimente'))

import qrcode
import io
import base64
from models import Pontaj, Confirmare

@app.route('/pontaj/<int:eveniment_id>')
@login_required
def pontaj(eveniment_id):
    e = db.session.get(Eveniment, eveniment_id)
    if not e:
        flash('Evenimentul nu a fost gasit.', 'danger')
        return redirect(url_for('evenimente'))
    voluntari_activi = Voluntar.query.filter_by(activ=True).order_by(Voluntar.departament, Voluntar.nume).all()
    pontaje_existente = {p.voluntar_id: p for p in Pontaj.query.filter_by(eveniment_id=eveniment_id).all()}
    pontaje_json = {p.voluntar_id: p.status for p in Pontaj.query.filter_by(eveniment_id=eveniment_id).all()}
    return render_template('pontaj.html', e=e,
                           voluntari=voluntari_activi,
                           pontaje=pontaje_existente,
                           pontaje_json=pontaje_json)

@app.route('/pontaj/<int:eveniment_id>/marcheaza', methods=['POST'])
@login_required
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

@app.route('/qr/<int:voluntar_id>')
@login_required
def qr_voluntar(voluntar_id):
    v = db.session.get(Voluntar, voluntar_id)
    url = f'http://localhost:5000/checkin/{voluntar_id}'
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode()
    return render_template('qr.html', v=v, img_b64=img_b64, url=url)

@app.route('/init-db-secret-rapid1923')
def init_db():
    from werkzeug.security import generate_password_hash
    db.create_all()
    from models import Voluntar
    admin = Voluntar.query.filter_by(email='admin@rapid.ro').first()
    if not admin:
        admin = Voluntar(
            nume='Admin',
            prenume='Rapid',
            email='admin@rapid.ro',
            parola=generate_password_hash('Rapid1923!'),
            rol='admin'
        )
        db.session.add(admin)
        db.session.commit()
        return 'Admin creat cu succes!'
    return 'Admin exista deja!'

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
        return render_template('checkin_result.html', v=v, mesaj='Nu există niciun eveniment activ în acest moment.', ok=False)
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

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)