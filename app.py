from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///parking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

from models import db, User, ParkingLot, ParkingSpot, ParkingBooking
db.init_app(app)

# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash('Admin access required', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            
            flash('Logged in successfully!', 'success')
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('user_dashboard'))
            
        flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('register'))
            
        if username.lower() == 'admin':
            flash('This username is not allowed', 'error')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        
        try:
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except:
            db.session.rollback()
            flash('Error occurred during registration', 'error')
            
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    parking_lots = ParkingLot.query.all()
    return render_template('admin_dashboard.html', parking_lots=parking_lots)

@app.route('/admin/parking-lots/add', methods=['GET', 'POST'])
@admin_required
def add_lot():
    if request.method == 'POST':
        name = request.form['name']
        location = request.form['location']
        total_spots = int(request.form['total_spots'])
        price_per_hour = float(request.form['price_per_hour'])

        lot = ParkingLot(name=name, location=location, total_spots=total_spots, price_per_hour=price_per_hour)
        
        try:
            # Commit the lot first to generate its ID
            db.session.add(lot)
            db.session.commit()

            # Now add parking spots
            for i in range(1, total_spots + 1):
                spot = ParkingSpot(spot_number=f"{i:03d}", lot_id=lot.id)
                db.session.add(spot)
            
            db.session.commit()
            flash('Parking lot added successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        
        except Exception as e:
            import traceback
            db.session.rollback()
            print("ERROR:", e)
            traceback.print_exc()
            flash('Error occurred while adding parking lot', 'error')

    return render_template('add_lot.html')


@app.route('/user/dashboard')
@login_required
def user_dashboard():
    active_bookings = ParkingBooking.query.filter_by(
        user_id=session['user_id'],
        status='active'
    ).all()
    completed_bookings = ParkingBooking.query.filter_by(
        user_id=session['user_id'],
        status='completed'
    ).all()

    return render_template(
        'user_dashboard.html',
        bookings=active_bookings,
        completed_bookings=completed_bookings
    )

    
@app.route('/user/book-spot', methods=['GET', 'POST'])
@login_required
def book_spot():
    if request.method == 'POST':
        lot_id = request.form['lot_id']
        vehicle_number = request.form['vehicle_number']
        
        # Find available spot in the selected lot
        available_spot = ParkingSpot.query.filter_by(
            lot_id=lot_id,
            is_occupied=False
        ).first()
        
        if available_spot:
            booking = ParkingBooking(
                user_id=session['user_id'],
                spot_id=available_spot.id,
                vehicle_number=vehicle_number
            )
            available_spot.is_occupied = True
            
            db.session.add(booking)
            try:
                db.session.commit()
                flash('Spot booked successfully!', 'success')
                return redirect(url_for('user_dashboard'))
            except:
                db.session.rollback()
                flash('Error occurred while booking spot', 'error')
        else:
            flash('No spots available in selected lot', 'error')
            
    parking_lots = ParkingLot.query.all()
    return render_template('book_spot.html', parking_lots=parking_lots)

@app.route('/user/exit-parking/<int:booking_id>')
@login_required
def exit_parking(booking_id):
    booking = ParkingBooking.query.get_or_404(booking_id)
    
    if booking.user_id != session['user_id']:
        flash('Unauthorized access', 'error')
        return redirect(url_for('user_dashboard'))
        
    booking.exit_time = datetime.now()
    hours_parked = (booking.exit_time - booking.entry_time).total_seconds() / 3600
    price_per_hour = booking.spot.lot.price_per_hour
    booking.total_charge = round(hours_parked * price_per_hour, 2)
    booking.status = 'completed'
    booking.spot.is_occupied = False
    
    try:
        db.session.commit()
        flash(f'Thank you for using our parking service! Your total charge is rs {booking.total_charge:.2f}', 'success')
    except:
        db.session.rollback()
        flash('Error occurred while processing exit', 'error')
        
    return redirect(url_for('user_dashboard'))

@app.route('/admin/reports')
@admin_required
def view_reports():
    active_bookings = ParkingBooking.query.filter_by(status='active').all()
    completed_bookings = ParkingBooking.query.filter_by(status='completed').all()
    return render_template('reports.html', 
                         active_bookings=active_bookings, 
                         completed_bookings=completed_bookings)

@app.route('/delete_lot/<int:lot_id>', methods=['POST'])
def delete_lot(lot_id):
    lot = ParkingLot.query.get_or_404(lot_id)
    occupied_spots = ParkingSpot.query.filter_by(lot_id=lot.id, is_occupied=True).count()

    if occupied_spots > 0:
        flash("Cannot delete lot. Some spots are still occupied.", "warning")
        return redirect(url_for('admin_dashboard'))

    # First delete associated spots
    ParkingSpot.query.filter_by(lot_id=lot.id).delete()
    db.session.delete(lot)
    db.session.commit()
    flash("Lot deleted successfully.", "success")
    return redirect(url_for('admin_dashboard'))


                        

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create admin user if it doesn't exist
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(
                username='admin',
                password=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.commit()
    app.run(debug=True)
