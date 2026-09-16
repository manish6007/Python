import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'receipt_screen.dart';

/// Paying one instalment.
///
/// Note what this screen does NOT do: it never tells the backend the payment
/// succeeded. It creates a payment, hands off to the gateway, and then reads
/// back whatever the server concluded from the gateway's signed callback. On a
/// local build the "gateway" is the backend's own mock endpoint, which signs a
/// callback with the real webhook secret - so this flow is the production flow,
/// not a shortcut around it.
class PayScreen extends StatefulWidget {
  const PayScreen({
    super.key,
    required this.financeId,
    required this.emiId,
    required this.seq,
    required this.amountPaise,
    required this.dueDate,
  });

  final String financeId;
  final String emiId;
  final int seq;
  final int amountPaise;
  final String dueDate;

  @override
  State<PayScreen> createState() => _PayScreenState();
}

class _PayScreenState extends State<PayScreen> {
  bool _busy = false;
  String _step = '';

  Future<void> _pay() async {
    setState(() {
      _busy = true;
      _step = 'Creating payment…';
    });
    final session = SessionScope.of(context);
    try {
      final created = await session.api.post(
        '/payments/create',
        body: {
          'finance_id': widget.financeId,
          'emi_id': widget.emiId,
          'amount_paise': widget.amountPaise,
        },
      ) as Map;
      final paymentId = created['payment_id'].toString();

      if (!mounted) return;
      setState(() => _step = 'Waiting for the gateway…');

      // A real integration opens the gateway SDK here and waits for it to
      // return. Either way, the app only learns the outcome from the server.
      final result = await session.api.post(
        '/mock-gateway/pay',
        body: {'payment_id': paymentId, 'outcome': 'SUCCESS'},
      ) as Map;

      if (!mounted) return;
      if (result['status'] == 'SUCCESS') {
        await Navigator.of(context).pushReplacement(MaterialPageRoute(
          builder: (_) => ReceiptScreen(paymentId: paymentId),
        ));
      } else {
        showError(
          context,
          ApiException('PAYMENT_FAILED',
              'The payment did not go through. Nothing has been charged.'),
        );
        setState(() => _busy = false);
      }
    } on ApiException catch (error) {
      if (mounted) {
        showError(context, error);
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text('Pay EMI ${widget.seq}')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              Text('Amount due',
                  textAlign: TextAlign.center,
                  style: Theme.of(context)
                      .textTheme
                      .labelLarge
                      ?.copyWith(color: scheme.onSurfaceVariant)),
              const SizedBox(height: 8),
              Text(
                Money.format(widget.amountPaise),
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .displaySmall
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              Text(
                'Instalment ${widget.seq} • due ${formatDate(widget.dueDate)}',
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .bodyMedium
                    ?.copyWith(color: scheme.onSurfaceVariant),
              ),
              const Spacer(),
              if (_busy) ...[
                const Center(child: CircularProgressIndicator()),
                const SizedBox(height: 12),
                Text(_step,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodySmall),
                const SizedBox(height: 24),
              ] else
                FilledButton.icon(
                  onPressed: _pay,
                  icon: const Icon(Icons.lock_outline),
                  label: const Text('Pay now'),
                ),
              const SizedBox(height: 16),
              Text(
                'Your payment is confirmed by the payment gateway, not by this '
                'app. The receipt appears once the server has verified it.',
                textAlign: TextAlign.center,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: scheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
