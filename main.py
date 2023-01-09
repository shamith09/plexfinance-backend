from flask import Flask, request, jsonify
from dotenv import load_dotenv
from bson.objectid import ObjectId
from os import getenv
from random import randint
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, unset_jwt_cookies, jwt_required, JWTManager
from datetime import datetime, timedelta, timezone
from send_email import gmail_send_message
import bcrypt
import pymongo
import json
from time import time

load_dotenv()

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = "please-remember-to-change-me"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
jwt = JWTManager(app)


@app.after_request
def after_request(response):
    # cors
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers',
                         'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods',
                         'GET,PUT,POST,DELETE,OPTIONS')

    # refresh expiring jwt
    try:
        exp_timestamp = get_jwt()["exp"]
        now = datetime.now(timezone.utc)
        target_timestamp = datetime.timestamp(now + timedelta(minutes=30))
        if target_timestamp > exp_timestamp:
            access_token = create_access_token(identity=get_jwt_identity())
            data = response.get_json()
            if type(data) is dict:
                data["access_token"] = access_token
                response.data = json.dumps(data)
        return response
    except (RuntimeError, KeyError):
        # Case where there is not a valid JWT. Just return the original respone
        return response


client = pymongo.MongoClient(
    f'mongodb+srv://{getenv("MONGO_USERNAME")}:{getenv("MONGO_PASSWORD")}@cluster0.mkbc83o.mongodb.net/?retryWrites=true&w=majority')
db = client.test


def get_hashed_password(plain_text_password):
    return bcrypt.hashpw(plain_text_password, bcrypt.gensalt())


def check_password(plain_text_password, hashed_password):
    return bcrypt.checkpw(plain_text_password, hashed_password)


@app.route("/logout/", methods=["POST"])
@jwt_required()
def logout():
    response = jsonify({"msg": "logout successful"})
    unset_jwt_cookies(response)
    return response


@app.route("/change-password/", methods=['PUT', 'GET', 'POST'])
@jwt_required()
def protected_user_routes():
    if request.method == 'PUT':
        id = ObjectId(get_jwt_identity())

        db.Users.update_one(
            {'_id': id}, {'$set': {'password': get_hashed_password(dict(request.json)['password'])}, '$unset': {'reset_password': '', 'timestamp': ''}})
        return {}, 200

    form = dict(request.json)

    if request.method == 'POST':  # TODO: restrict to treasurer
        try:
            emails = form['emails']

            query = [{'email': email} for email in emails]

            db.Users.insert_many(query)
        except:
            return {'error': 'Repeat emails'}, 500

        return {}, 200

    if request.method == 'GET':  # TODO: restrict to treasurer
        try:
            users = db.Users.find({})

        except:
            return {'error': 'Internal Server Error'}, 500

        signed_up, not_signed_up = [], []
        for user in users:
            user['_id'] = str(user['_id'])
            if 'password' in user:
                signed_up.append(user)
            else:
                not_signed_up.append(user)

        return {'signedUp': signed_up, 'notSignedUp': not_signed_up}, 200


@app.route('/users/', methods=['POST'])
def login_signup_add_PIC():
    form = dict(request.json)

    try:
        user = db.Users.find_one({'email': form['email']})

        if not user:
            return {'error': 'Incorrect email'}, 401
        if form['method'] == 'login' and 'google' in form and form['google']:
            if 'google' not in user:
                return {}, 404
    except:
        return {'error': 'Bad Request'}, 400

    if form['method'] == 'login':
        # login success
        if user['google'] or check_password(form['password'], user['password']):
            access_token = create_access_token(identity=str(user['_id']))
            response = {'access_token': access_token}
            return response, 200
        else:
            return {'error': 'Incorrect password'}, 401

    if form['method'] == 'signup':
        del form['method']
        form['requests'] = []
        if 'google' in form and form['google']:
            db.Users.replace_one({'_id': user['_id']}, form)
        else:
            if 'password' not in user:
                return {'error': 'Account already exists'}, 400

            form['password'] = get_hashed_password(form['password'])
            db.Users.replace_one({'_id': user['_id']}, form)

        access_token = create_access_token(identity=str(user['_id']))
        response = {'access_token': access_token}
        return response, 200

    if form['method'] == 'passwordCode':
        number = str(randint(10000, 99999))
        db.Users.update_one({'_id': user['_id']}, {
                            '$set': {'reset_password': get_hashed_password(number), 'timestamp': time()}})

        gmail_send_message(form['email'], f'[PlexTech] Reset Password Code',
                           f'Your 5-digit password reset code is: {number}. This code will expire in 5 minutes.')

        return {}, 200

    if form['method'] == 'checkResetPasswordCode':
        if time() - user['timestamp'] >= 300:
            return {'error': 'Expired code'}, 498
        if check_password(form['code'], user['reset_password']):
            access_token = create_access_token(identity=str(user['_id']))
            response = {'access_token': access_token}
            return response, 200
        else:
            return {'error': 'Incorrect code'}, 401


@app.route('/requests/', methods=['GET', 'POST', 'PUT'])
@jwt_required()
def request_by_id():
    id = ObjectId(get_jwt_identity())

    if request.method == 'GET':
        user = dict(db.Users.find_one({'_id': id}))
        response = db.Requests.find({'_id': {'$in': user['requests']}})

        res = {
            'pendingReview': [],
            'underReview': [],
            'errors': [],
            'approved': [],
            'declined': [],
        }
        for r in response:
            r['_id'] = str(r['_id'])
            res[r['status']].append(r)
        return res, 200

    if request.method == 'POST':
        form = dict(request.json)
        res = db.Requests.insert_one(form)
        request_id = str(res.inserted_id)
        db.Users.find_one_and_update(
            {'_id': id}, {'$push': {'requests': ObjectId(request_id)}})


        form['_id'] = request_id
        del form['images']
        return form, 200

    if request.method == 'PUT':
        form = dict(request.json)
        request_id = form['_id']
        del form['_id']
        # try:
        res = db.Requests.replace_one({'_id': ObjectId(request_id)}, form)
        if res.matched_count == 0:
            db.Requests.insert_one(form)
        # except:
        #     return {'error': 'Internal Server Error'}, 500
        return {'_id': str(id)}, 200


if __name__ == '__main__':
    app.run(debug=True, port=5001)
