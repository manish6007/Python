# Running EMI Locker on Windows

Start to finish, from a clean Windows PC to both apps running against your own
backend. Expect **60–90 minutes**, most of it downloads.

You need the backend running, plus whichever front end you are using:

| Part | What it is | Where it runs |
|---|---|---|
| **Backend** | Python API + database | A terminal window on your PC |
| **Apps** | Customer, Retailer, Distributor | Android emulator, or a real phone |
| **Admin panel** | Super Admin web panel | Chrome on your PC |

All four front ends are one Flutter project. The role you sign in as decides
which one you get, so there is nothing extra to install for the admin panel.

---

## Step 1 — Install Python

1. Go to <https://www.python.org/downloads/windows/> and get the latest
   **Python 3.11 or newer** (64-bit installer).
2. Run the installer. **Tick "Add python.exe to PATH"** on the first screen —
   this is the box everyone misses, and skipping it is the cause of most
   "python is not recognized" errors later.
3. Open **Command Prompt** and check:

   ```bat
   python --version
   ```

   You should see `Python 3.11.x` or newer.

## Step 2 — Install Android Studio

Android Studio brings the Android SDK, the emulator and the device drivers.
You need it even though we are writing Flutter, not Java.

1. Download from <https://developer.android.com/studio> and install with the
   default options.
2. Launch it once and let the setup wizard finish downloading the SDK.
3. **Create an emulator**: *More Actions* → *Virtual Device Manager* → *Create
   Device* → pick **Pixel 7** → pick a system image (any recent API level;
   download it if prompted) → *Finish*.
4. Press ▶ on the device to check it boots. Leave it running or close it — the
   Flutter command can start it for you later.

> **If the emulator will not start**, virtualization is probably off. Reboot
> into BIOS/UEFI and enable *Intel VT-x* or *AMD-V*. On some machines you also
> need to turn on *Windows Hypervisor Platform* in "Turn Windows features on or
> off". If you cannot get the emulator working, skip to
> [Using a real phone](#using-a-real-phone-instead-of-the-emulator).

## Step 3 — Install Flutter

1. Download the Flutter SDK for Windows from
   <https://docs.flutter.dev/get-started/install/windows>.
2. Unzip it to `C:\src\flutter`. **Do not** put it in `C:\Program Files` — the
   space in the path and the permissions both cause trouble.
3. Add `C:\src\flutter\bin` to your PATH:
   *Start* → search "environment variables" → *Edit the system environment
   variables* → *Environment Variables…* → under **User variables** select
   `Path` → *Edit* → *New* → paste `C:\src\flutter\bin` → OK on every window.
4. **Open a new Command Prompt** (PATH changes only apply to new windows) and
   run:

   ```bat
   flutter doctor --android-licenses
   flutter doctor
   ```

   Accept the licences (type `y` to each). `flutter doctor` should show ticks
   for **Flutter** and **Android toolchain**. Chrome and Visual Studio warnings
   do not matter — we are not building for web or Windows desktop.

## Step 4 — Get the code

```bat
cd C:\src
git clone https://github.com/manish6007/Python.git
cd Python
git checkout claude/platform-feasibility-6jfldh
cd emi_locker
```

## Step 5 — Start the backend

In Command Prompt, from the `emi_locker` folder:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
python -m backend.seed
python -m backend.app.main
```

Or just double-click **`start-backend.bat`**, which does all of the above.

You should see:

```
EMI Locker API on http://0.0.0.0:8000  (docs at /docs)
```

**Leave this window open.** The backend has to keep running while you use the
app. To stop it, press `Ctrl+C`.

The seed step prints the numbers you will sign in with:

```
  Retailer app    9000000003   Sharma Mobiles
  Retailer app    9000000004   Verma Telecom
  Customer app    9876543210   Ramesh Kumar (has a live finance)
  Customer app    9876543211   Sunita Devi (no finance yet)
  Distributor app 9000000002   North Distributor
  Admin panel     9000000001   Ashish Enterprises (web)
```

**Check it works**: open <http://localhost:8000/docs> in your browser. You
should see the API documentation page, where you can also try endpoints by
hand.

## Step 6 — Run the app

Open a **second** Command Prompt (leave the backend running in the first):

```bat
cd C:\src\Python\emi_locker\mobile\emi_locker_app
flutter pub get
flutter run
```

Flutter will start your emulator if it is not already running, build the app
(the first build takes several minutes — later ones are seconds) and install
it.

That is it. The app opens on the sign-in screen.

## Step 6b — Open the admin panel

The Super Admin panel is the same project, run in Chrome instead. In a **third**
Command Prompt:

```bat
cd C:\src\Python\emi_locker\mobile\emi_locker_app
flutter run -d chrome
```

Chrome opens automatically. Sign in with **9000000001**.

> On web the app talks to `http://localhost:8000` by itself — `10.0.2.2` is an
> emulator-only address and means nothing in a browser. You do not have to
> configure anything.

To build a copy you can serve to other people on your network instead:

```bat
flutter build web
python -m http.server 8080 --directory build\web
```

then open <http://localhost:8080>. The panel is fully self-contained: the
graphics engine and fonts are served from the build, so it works on a machine
with no internet at all.

---

## Step 7 — Try the whole flow

The point of running both apps is to watch a finance go from sale to
settlement. Do it in this order.

### As the retailer

1. Sign in with **9000000003**. The OTP is filled in for you — local mode
   returns it instead of sending an SMS. (You can also read it in the backend
   window: `[OTP] 9000000003 -> 482910`.)
2. **Dashboard** — note the activation balance: 99 of 100. Each new finance
   spends one.
3. **Customers** → **Add customer**. Use any name and a fresh 10-digit number,
   for example `9555500001`. Remember it; you will sign in as this customer.
4. Open the customer you just created. **New finance** is greyed out — tick all
   three consents first. The backend refuses a finance without them, so this is
   not just a UI nicety.
5. **New finance** → IMEI `356938035643809` (a valid spare from the seed) →
   price `24000`, down payment `6000`, tenure `9` → **Calculate EMI**.
6. Check the agreement figures, then **Customer agrees — activate finance**.
   Go back to the dashboard: the balance is now 98.

### Try to break it

These should all fail, and the message should tell you why:

- Start another finance for a different customer with the **same IMEI** →
  *"IMEI … is already on live finance"*.
- Enter an IMEI with a typo (`490154203237519`) → caught before it even
  reaches the server.
- Add a customer with a mobile number you have already used → *"mobile … is
  already registered"*.

### As the customer

7. Sign out (Profile → Sign out), then sign in with **9876543210**
   (Ramesh Kumar, who already has a ₹22,000 / 11-month finance from the seed).
8. Tap the card → the full schedule → **Pay EMI 1 ₹2,000**.
9. Watch the backend window: a payment is created, then the mock gateway posts
   a *signed* callback, and only then is the EMI marked paid. The receipt
   appears. **Payments** shows the history.

### Back as the retailer

10. Sign in as **9000000003** again. Dashboard → **Run the daily status sweep**.
    This is the nightly job, triggered by hand so you do not have to wait. It
    moves instalments to due / grace / overdue.
11. **Collections** now lists what to chase. Tap one → **Confirm collection** →
    a cash receipt is issued. The customer sees the same receipt in their app.

### As the distributor

12. Sign out and sign in with **9000000002**. The dashboard shows activation
    stock: 350 of 500 left, 150 already pushed down to retailers.
13. **Retailers** lists Sharma Mobiles and Verma Telecom with the two numbers a
    distributor acts on — activations left, and money outstanding.
14. Open one → **Allocate activations** → 25 → **Allocate**. Their balance goes
    up, yours goes down. Try allocating 10,000 and it is refused: you cannot
    hand out stock you do not hold.
15. **Commission** says no rate has been configured. That is deliberate — the
    rates are a business decision, set in the admin panel, and the software
    does not invent one. You will set it in the next section.

### As the Super Admin (in Chrome)

16. In the browser, sign in with **9000000001**.
17. **Network** shows the distributor with its two retailers. Try the ⊘ button
    on Sharma Mobiles: suspending needs a reason, which goes into the audit
    log. Suspend them, then switch to the retailer app — they are locked out
    immediately, not at their next login. Reactivate them afterwards.
18. **Licences** → **Issue licence** → pick BUSINESS → **Issue**. The key is
    shown once and stored only as a hash. Copy it, then sign in as
    **9000000004** on the phone and redeem it under Licences.
19. **Settings** → change *Paid to the retailer for each device it activates*
    to ₹150. Go back to the distributor app: Commission now shows real
    figures.
20. **Audit log** shows every one of those actions, with who did it and what
    the value was before. Nothing in the panel can edit or delete it — the
    database rejects any attempt.

---

## Using a real phone instead of the emulator

Emulators are heavy. A real Android phone is often easier.

1. On the phone: *Settings* → *About phone* → tap **Build number** seven times
   → go back → *Developer options* → turn on **USB debugging**.
2. Plug it in by USB and accept the "Allow USB debugging?" prompt.
3. Check Windows sees it: `flutter devices`.
4. **The phone cannot reach `10.0.2.2`** — that address only means anything to
   the emulator. Find your PC's LAN address:

   ```bat
   ipconfig
   ```

   Look for *IPv4 Address* under your Wi-Fi adapter, for example
   `192.168.1.5`. Then run the app pointed at it:

   ```bat
   flutter run --dart-define=API_BASE_URL=http://192.168.1.5:8000
   ```

5. The phone and the PC must be on the **same Wi-Fi network**, and Windows
   Firewall must allow it. If the app cannot connect, allow Python through the
   firewall: *Windows Security* → *Firewall & network protection* →
   *Allow an app through firewall* → *Change settings* → *Allow another app* →
   browse to `C:\src\Python\emi_locker\.venv\Scripts\python.exe` → tick
   **Private**.

---

## Troubleshooting

**"Cannot reach the server at http://10.0.2.2:8000"**
The app says this when the backend is not reachable. In order:
1. Is the backend window still open and showing no error?
2. Does <http://localhost:8000/health> load in your browser?
3. On a real phone, did you pass `--dart-define=API_BASE_URL=...`? See above.

**"python is not recognized"**
Python was installed without "Add to PATH". Re-run the installer, choose
*Modify*, and tick it — or reinstall.

**"flutter is not recognized"**
`C:\src\flutter\bin` is not on your PATH, or you did not open a **new**
Command Prompt after adding it.

**`flutter doctor` complains about Android licences**
Run `flutter doctor --android-licenses` and accept each one.

**Gradle takes forever on the first build**
Normal. It is downloading the Android build toolchain. Later builds are fast.
Do not interrupt it.

**The app shows old data**
Pull down on any list to refresh.

**The admin panel is a blank white page**
Rebuild it: `flutter build web`. The graphics engine is served from the build
itself, so a blank page usually means an old build is being served from a
stale folder. Hard-refresh the browser with `Ctrl+Shift+R`.

**The admin panel cannot reach the backend**
In a browser the address is `localhost:8000`, not `10.0.2.2:8000`. That is
automatic — if you have overridden `API_BASE_URL` with an emulator address,
remove it for the web run.

**I want to start over with clean data**
Stop the backend (`Ctrl+C`) and run:

```bat
python -m backend.seed --reset
```

**Port 8000 is already in use**

```bat
set EMI_PORT=8001
python -m backend.app.main
```

and run the app with
`flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8001`.

---

## What is deliberately not real yet

So you are not surprised:

- **OTPs are not sent by SMS.** Local mode returns the code in the response and
  prints it in the backend window. Wiring a real SMS provider is a later step.
- **Payments do not move money.** The "gateway" is a local stand-in. It is
  built to be honest about the *flow* — it signs a callback with the real
  webhook secret and the backend verifies it, exactly as a production gateway
  will — but no rupee changes hands.
- **No phone is actually locked.** Device restriction is recorded, approved and
  audited, and the default provider reports that nothing was sent, because an
  ordinary app genuinely cannot restrict a device. That needs an Android
  Enterprise EMM. See §3.1 of [FEASIBILITY.md](../FEASIBILITY.md).
- **The data lives in a file** (`emi_locker.db`) next to the backend. Delete it
  to start fresh. Production would use PostgreSQL.
- **All four front ends are one project here**, and the role you sign in as
  decides what you see. For release, Customer, Retailer and Distributor become
  three Play listings and the admin panel a hosted web build; the code is
  already split into `features/customer`, `features/retailer`,
  `features/distributor` and `features/admin`, so that is a move rather than a
  rewrite.
- **Commission rates start at zero** and stay there until an admin sets them.
  The blueprint lists possible commission structures but fixes no rate, because
  that is a commercial decision — so the software shows "not configured"
  instead of inventing a percentage.
