import os
from twilio.rest import Client

from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# Set up Twilio client.
account_sid = os.environ.get("ACCOUNT_SID")
auth_token = os.environ.get("AUTH_TOKEN")
client = Client(account_sid, auth_token)

@app.route("/answer/", methods=['GET', 'POST'])
def answer_call():
    """Respond to incoming phone calls with a brief message."""
    # Start our TwiML response
    resp = VoiceResponse()

    # Play music
    resp.play('https://api.twilio.com/cowbell.mp3', loop=0)

    return str(resp)

@app.route("/sms/reply/", methods=['GET', 'POST'])
def sms_reply():
    body = request.values.get('Body', None)
    phone = request.values.get('From', None)
    # Start our TwiML response.
    resp = MessagingResponse()

    # Add a text message
    msg = resp.message("Your Phone Number is: %s" % phone)

    return str(resp)

@app.route("/send-sms/<user_phone>", methods=['POST'])
def send_message():
    user_phone = user_phone
    message = client.messages.create(
                body='Hi there!',
                from_=os.environ.get("TWILIO_NUMBER"),
                to=str(user_phone)
            )

    return message.sid

@app.route("/place-call/<user_phone>", methods=['POST'])
def place_call():
    user_phone = user_phone
    call = client.calls.create(
                url='http://demo.twilio.com/docs/voice.xml',
                from_=os.environ.get("TWILIO_NUMBER"),
                to=str(user_phone),
            )

    return call.sid

if __name__ == "__main__":
    app.run(debug=True)