from flask import Flask, request
from dotenv import load_dotenv
from bson.objectid import ObjectId
from os import getenv
import pymongo

load_dotenv()

app = Flask(__name__)


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers',
                         'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods',
                         'GET,PUT,POST,DELETE,OPTIONS')
    return response


client = pymongo.MongoClient(
    f'mongodb+srv://{getenv("MONGO_USERNAME")}:{getenv("MONGO_PASSWORD")}@cluster0.mkbc83o.mongodb.net/?retryWrites=true&w=majority')
db = client.test


@app.route('/requests/', methods=['GET', 'POST', 'DELETE'])
@app.route('/requests/<id>', methods=['GET', 'PUT'])
def request_by_id(id=None):
    if request.method == 'GET' and id:
        try:
            res = db.Requests.find_one(ObjectId(id))
        except:
            return {'error': 'Bad Request'}, 400

        if not res:
            return {'error': 'Not Found'}, 404

        res['_id'] = str(res['_id'])
        return res, 200

    if request.method == 'GET' and not id:
        try:
            response = db.Requests.find({})
        except:
            return {'error': 'Internal Server Error'}, 500

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
        try:
            res = db.Requests.insert_one(form)
        except:
            return {'error': 'Internal Server Error'}, 500

        form['_id'] = str(res.inserted_id)
        del form['images']
        return form, 200

    if request.method == 'PUT':
        form = dict(request.json)
        del form['_id']
        # try:
        res = db.Requests.replace_one({'_id': ObjectId(id)}, form)
        if res.matched_count == 0:
            db.Requests.insert_one(form)
        # except:
        #     return {'error': 'Internal Server Error'}, 500
        return {'_id': id}, 200

    if request.method == 'DELETE':
        db.Requests.delete_many({})
        return {'message': 'success'}, 200


if __name__ == '__main__':
    app.run(debug=True, port=3000)
