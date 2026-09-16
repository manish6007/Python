import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// Who is signed in, and the token used to prove it.
///
/// The token is kept in SharedPreferences so the app does not ask for an OTP
/// on every launch. That is fine for local testing; a production build should
/// move it to the Android Keystore via flutter_secure_storage.
class Session extends ChangeNotifier {
  Session(this.api);

  final ApiClient api;

  static const _tokenKey = 'emi.token';
  static const _userKey = 'emi.user';

  Map<String, dynamic>? _user;
  bool _restoring = true;

  Map<String, dynamic>? get user => _user;
  bool get isRestoring => _restoring;
  bool get isSignedIn => _user != null && api.token != null;

  String get role => _user?['role']?.toString() ?? '';
  String get displayName => _user?['name']?.toString() ?? '';
  String get mobile => _user?['mobile']?.toString() ?? '';
  String? get customerId => _user?['customer_id']?.toString();
  String? get retailerId => _user?['retailer_id']?.toString();

  bool get isRetailer => role == 'RETAILER' || role == 'STAFF';
  bool get isCustomer => role == 'CUSTOMER';

  /// Reload a previous sign-in, if the saved token is still valid.
  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenKey);
    final rawUser = prefs.getString(_userKey);
    if (token != null && rawUser != null) {
      api.token = token;
      _user = jsonDecode(rawUser) as Map<String, dynamic>;
      try {
        // Confirm with the server: the token may have expired, or the account
        // may have been suspended since the last launch.
        _user = Map<String, dynamic>.from(await api.get('/auth/me') as Map);
        await prefs.setString(_userKey, jsonEncode(_user));
      } on ApiException {
        await _clear(prefs);
      }
    }
    _restoring = false;
    notifyListeners();
  }

  Future<void> signIn(String token, Map<String, dynamic> user) async {
    api.token = token;
    _user = user;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
    await prefs.setString(_userKey, jsonEncode(user));
    notifyListeners();
  }

  Future<void> signOut() async {
    await _clear(await SharedPreferences.getInstance());
    notifyListeners();
  }

  Future<void> _clear(SharedPreferences prefs) async {
    api.token = null;
    _user = null;
    await prefs.remove(_tokenKey);
    await prefs.remove(_userKey);
  }
}
