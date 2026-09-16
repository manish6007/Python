import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/session.dart';
import 'core/theme.dart';
import 'features/auth/login_screen.dart';
import 'features/customer/customer_shell.dart';
import 'features/retailer/retailer_shell.dart';

void main() {
  runApp(EmiLockerApp(api: ApiClient()));
}

/// One app, two audiences.
///
/// The role that comes back from sign-in decides which shell you land in:
/// a retailer never sees the customer screens and vice versa. For production
/// these become two Play listings - the feature folders are already separate,
/// so splitting them is moving `features/customer` and `features/retailer`
/// into two projects that share `core/`.
class EmiLockerApp extends StatefulWidget {
  const EmiLockerApp({super.key, required this.api});

  final ApiClient api;

  @override
  State<EmiLockerApp> createState() => _EmiLockerAppState();
}

class _EmiLockerAppState extends State<EmiLockerApp> {
  late final Session _session = Session(widget.api);

  @override
  void initState() {
    super.initState();
    _session.restore();
  }

  @override
  Widget build(BuildContext context) {
    // SessionScope sits ABOVE MaterialApp on purpose. MaterialApp builds the
    // Navigator, so anything below it is a sibling of pushed routes, not an
    // ancestor - a scope placed in `home:` would be invisible to every screen
    // the app navigates to.
    return SessionScope(
      session: _session,
      child: MaterialApp(
        title: 'EMI Locker',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        home: AnimatedBuilder(
          animation: _session,
          builder: (context, _) {
            if (_session.isRestoring) {
              return const Scaffold(
                body: Center(child: CircularProgressIndicator()),
              );
            }
            if (!_session.isSignedIn) {
              return const LoginScreen();
            }
            if (_session.isRetailer) {
              return const RetailerShell();
            }
            if (_session.isCustomer) {
              return const CustomerShell();
            }
            return _UnsupportedRole(session: _session);
          },
        ),
      ),
    );
  }
}

/// Makes the session reachable from any screen without a state-management
/// package. `SessionScope.of(context)` is the only way screens get the API.
class SessionScope extends InheritedWidget {
  const SessionScope({super.key, required this.session, required super.child});

  final Session session;

  static Session of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<SessionScope>();
    assert(scope != null, 'No SessionScope above this widget');
    return scope!.session;
  }

  @override
  bool updateShouldNotify(SessionScope oldWidget) => session != oldWidget.session;
}

class _UnsupportedRole extends StatelessWidget {
  const _UnsupportedRole({required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.info_outline, size: 48),
              const SizedBox(height: 16),
              Text(
                'The ${session.role} role is managed from the admin web panel, '
                'not from this app.',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              OutlinedButton(
                onPressed: session.signOut,
                child: const Text('Sign out'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
