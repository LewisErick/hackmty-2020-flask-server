import os
from twilio.rest import Client

account_sid = os.environ.get("ACCOUNT_SID")
auth_token = os.environ.get("AUTH_TOKEN")
client = Client(account_sid, auth_token)

message = client.messages.create(
                              body='Hi there!',
                              from_='+19142299068',
                              to='+528110801708'
                          )

print(message.sid)
