import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/request_id.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import '../customer/receipt_screen.dart';

/// Recording a cash collection.
///
/// The amount is fixed to the instalment rather than typed: the backend
/// refuses a mismatch anyway, and a free-text amount on a busy shop counter is
/// how cash goes missing. The idempotency key is created once so a double tap
/// on a slow connection cannot take the money twice.
class CollectScreen extends StatefulWidget {
  const CollectScreen({
    super.key,
    required this.financeId,
    required this.emiId,
    required this.seq,
    required this.amountPaise,
    required this.customerName,
    required this.mobile,
  });

  final String financeId;
  final String emiId;
  final int seq;
  final int amountPaise;
  final String customerName;
  final String mobile;

  @override
  State<CollectScreen> createState() => _CollectScreenState();
}

class _CollectScreenState extends State<CollectScreen> {
  final String _requestId = newRequestId('cash');
  String _mode = 'CASH';
  bool _busy = false;

  Future<void> _collect() async {
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      final result = await session.api.post(
        '/collections',
        idempotencyKey: _requestId,
        body: {
          'finance_id': widget.financeId,
          'emi_id': widget.emiId,
          'amount_paise': widget.amountPaise,
          'mode': _mode,
        },
      ) as Map;
      if (!mounted) return;
      await Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => ReceiptScreen(paymentId: result['payment_id'].toString()),
      ));
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
      appBar: AppBar(title: Text('Collect EMI ${widget.seq}')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Card(
            child: ListTile(
              leading: CircleAvatar(
                child: Text(
                    widget.customerName.characters.first.toUpperCase()),
              ),
              title: Text(widget.customerName),
              subtitle: Text('+91 ${widget.mobile}'),
            ),
          ),
          const SizedBox(height: 32),
          Text('Amount to collect',
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
          const SizedBox(height: 32),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                  value: 'CASH', label: Text('Cash'), icon: Icon(Icons.payments)),
              ButtonSegment(
                  value: 'OTHER',
                  label: Text('Other'),
                  icon: Icon(Icons.swap_horiz)),
            ],
            selected: {_mode},
            onSelectionChanged: _busy
                ? null
                : (selection) => setState(() => _mode = selection.first),
          ),
          const SizedBox(height: 32),
          FilledButton.icon(
            onPressed: _busy ? null : _collect,
            icon: _busy
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.check),
            label: const Text('Confirm collection'),
          ),
          const SizedBox(height: 16),
          Text(
            'A receipt is issued immediately and the customer can see it in '
            'their app. Collections are reconciled against your daily cash.',
            textAlign: TextAlign.center,
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: scheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}
