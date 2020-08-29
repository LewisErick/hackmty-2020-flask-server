import redis
import os
import json

from flask import Flask
from flask import request
from random import randint

app = Flask(__name__)
r = redis.Redis(host=os.environ['REDIS_HOST'], port=os.environ['REDIS_PORT'], db=0)

"""
Start an exam. It gets the id of the test and returns a random generated number
to identify this test in the flask server.
Expected data in the request:
{
  "exam_id": ID,
  "num_questions": Number,
}

Returns:
{
  "sms_id": String,
}
"""
@app.route('/start', methods=['POST'])
def start_exam():
  req_data = request.get_json()
  exam_id = req_data['exam_id']
  num_questions = req_data['num_questions']
  sms_id = register_exam(exam_id, num_questions)
  return {
    "sms_id": sms_id,
  }


def register_exam(exam_id, num_questions):
  sms_id = None
  while sms_id is None or r.exists(sms_id):
    sms_id = str(randint(0, 999999)).zfill(6)
  exam_data = {
    'exam_id': exam_id,
    'num_questions': num_questions,
  }
  json_data = json.dumps(exam_data)
  r.set(sms_id, json_data)
  return sms_id
