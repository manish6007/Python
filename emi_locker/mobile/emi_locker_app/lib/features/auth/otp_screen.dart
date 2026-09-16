import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api_client.dart';
import '../../core/widgets.dart';
import '../../main.dart';

class OtpScreen extends StatefulWidget {
  const OtpScreen({super.key, required this.mobile, this.devOtp});

  final String mobile;

  /// Only ever set by a local backend. Shown on screen so you can sign in
  /// without an SMS provider while testing.
  final String? devOtp;

  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  final _code = TextEditingController();
  bool _busy = false;
  int _resendIn = 30;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    // Prefill in local builds so testing the flow is not six taps of typing.
    if (widget.devOtp != null) _code.text = widget.devOtp!;
    _startCountdown();
  }

  void _startCountdown() {
    _timer?.cancel();
    setState(() => _resendIn = 30);
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) return timer.cancel();
      setState(() => _resendIn--);
      if (_resendIn <= 0) timer.cancel();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _code.dispose();
    super.dispose();
  }

  Future<void> _verify() async {
    if (_code.text.trim().length < 4) {
      showError(context, ApiException('LOCAL', 'Enter the 6-digit code'));
      return;
    }
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      final response = await session.api.post(
        '/auth/verify-otp',
        body: {'mobile': widget.mobile, 'code': _code.text.trim()},
      ) as Map;
      await session.signIn(
        response['token'].toString(),
        Map<String, dynamic>.from(response['user'] as Map),
      );
      // The root widget swaps to the right shell as soon as the session
      // changes, so this screen just gets out of the way.
      if (mounted) Navigator.of(context).popUntil((route) => route.isFirst);
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _resend() async {
    final session = SessionScope.of(context);
    try {
      final response = await session.api
          .post('/auth/send-otp', body: {'mobile': widget.mobile}) as Map;
      if (response['dev_otp'] != null) _code.text = response['dev_otp'].toString();
      _startCountdown();
      if (mounted) showOk(context, 'New code sent');
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Verify')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Enter the code',
                    style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 8),
                Text(
                  'Sent to +91 ${widget.mobile}',
                  style: Theme.of(context)
                      .textTheme
                      .bodyMedium
                      ?.copyWith(color: scheme.onSurfaceVariant),
                ),
                const SizedBox(height: 28),
                TextField(
                  controller: _code,
                  autofocus: true,
                  keyboardType: TextInputType.number,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 28, letterSpacing: 12),
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                    LengthLimitingTextInputFormatter(6),
                  ],
                  decoration: const InputDecoration(counterText: ''),
                  onSubmitted: (_) => _verify(),
                ),
                if (widget.devOtp != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: scheme.tertiaryContainer,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.science_outlined,
                            size: 18, color: scheme.onTertiaryContainer),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Local test mode: code filled in for you. A real '
                            'backend sends this by SMS only.',
                            style: TextStyle(
                                fontSize: 12, color: scheme.onTertiaryContainer),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: _busy ? null : _verify,
                  child: _busy
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Verify and sign in'),
                ),
                const SizedBox(height: 12),
                TextButton(
                  onPressed: _resendIn > 0 ? null : _resend,
                  child: Text(_resendIn > 0
                      ? 'Resend code in ${_resendIn}s'
                      : 'Resend code'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
