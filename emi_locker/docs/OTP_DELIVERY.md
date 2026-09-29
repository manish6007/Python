# Sending one-time codes

Sign-in is by OTP, so whatever delivers those codes is the front door to the
whole platform. If it stops working, nobody signs in and nobody pays.

The backend does not care which channel is used. Pick one with
`EMI_OTP_CHANNEL`; nothing else changes.

| Channel | What it is | Use it for |
|---|---|---|
| `console` | Prints the code to the server log | Local testing (the default) |
| `evolution` | [Evolution Go](https://github.com/evolution-foundation/evolution-go), an unofficial WhatsApp gateway | Pilots, with the warning below |
| `http` | Any JSON API — SMS aggregator or licensed WhatsApp provider | Production |

The API also returns the code in the response while `EMI_EXPOSE_OTP=1`, which
is why you can sign in locally with no provider at all. The app refuses to
start in production with that on.

---

## Evolution Go — read this first

Evolution Go is built on **whatsmeow**, which speaks the WhatsApp Web protocol
as an unofficial client. You pair it by scanning a QR code with a real
WhatsApp number.

That means:

- **It breaches WhatsApp's Terms of Service.** Meta bans numbers for the exact
  pattern OTP creates — high volumes of near-identical messages to people who
  have never messaged you first.
- **A ban locks every customer out.** Sign-in is the only way into the apps, so
  a banned number means no logins, no payments, and no way to reach your own
  customers. There is no SLA and no appeal.
- **The risk grows with success.** Ten codes a day attracts nothing. A thousand
  attracts attention.

It is reasonable for a pilot with a handful of retailers while you get official
access approved. It is not somewhere to leave the front door.

### Configuration

```bash
EMI_OTP_CHANNEL=evolution
EMI_WA_URL=http://localhost:8080
EMI_WA_INSTANCE=ashish-enterprises
EMI_WA_API_KEY=your-evolution-api-key
EMI_BUSINESS_NAME="Ashish Enterprises"
```

Run the gateway, create an instance, and scan the QR from
`GET /instance/{name}/qrcode` with the number you intend to send from — not
your personal number.

The backend then sends:

```
POST http://localhost:8080/message/sendText/ashish-enterprises
apikey: your-evolution-api-key

{
  "number": "919876543210",
  "text": "482910 is your Ashish Enterprises verification code. It is valid for 5 minutes. Do not share it with anyone."
}
```

---

## The official route

**WhatsApp Business Platform** (Cloud API) with an approved
**authentication-category template**. Either direct from Meta, or through a
Business Solution Provider — Gupshup, Twilio, Kaleyra, MSG91, Interakt and
AiSensy all serve India. Authentication conversations are billed per
conversation.

**SMS** as the fallback, because a customer without WhatsApp still has to sign
in. In India this needs **DLT registration** with TRAI: an entity ID, a
registered sender ID (header), and the message template registered in advance.
Your aggregator walks you through it, but it takes days to weeks — **start it
before you need it**, not when you are ready to launch.

Both fit the `http` channel:

```bash
EMI_OTP_CHANNEL=http
EMI_OTP_HTTP_URL=https://api.provider.example/v1/sms
EMI_OTP_HTTP_KEY=...
EMI_OTP_HTTP_AUTH_HEADER=Authorization      # or X-Api-Key, etc.
EMI_OTP_HTTP_TO_FIELD=to                    # every aggregator names it differently
EMI_OTP_HTTP_BODY_FIELD=message
```

Providers needing extra fields (a DLT template id, a sender header) take a
small adapter — `HttpChannel` already accepts `extra_fields`; wire your
provider's names in `notifications.py`.

**The registered DLT template and `EMI_OTP_TEMPLATE` must match exactly**, or
the aggregator silently drops the message. Set it explicitly:

```bash
EMI_OTP_TEMPLATE="{code} is your {business} verification code. It is valid for {minutes} minutes. Do not share it with anyone."
```

---

## What happens when delivery fails

A failure is **logged and swallowed**. `/auth/send-otp` answers identically
whether the code was delivered, the gateway was down, or the number has no
account at all.

That is deliberate. Reporting a delivery failure would report it only for
numbers that *have* an account, which turns the endpoint into a way to check
which mobile numbers are registered. The customer simply asks for another code.

So **watch the logs**. A banned WhatsApp number looks exactly like silence:

```
ERROR emi.otp OTP delivery failed via evolution for 98****10: evolution gateway rejected the message (HTTP 401)
```

A code that failed to send is still a valid code — issuance and delivery are
separate steps, so a customer who receives a delayed message can still use it.

## Receiving messages

Nothing in the OTP flow needs to *receive* anything: the customer reads the
code and types it into the app. Evolution Go does support inbound webhooks, and
that would be the way to build the Support/WhatsApp channel in §21 of the
blueprint — customers messaging the business and staff replying from the admin
panel. That is a separate feature and is not built.
