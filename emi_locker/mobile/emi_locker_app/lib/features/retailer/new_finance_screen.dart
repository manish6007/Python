import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/request_id.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// New finance: device details, pricing, then the agreement.
///
/// The EMI figures shown on the agreement step come from the backend's own
/// `/finance/quote`, not from arithmetic done here. If the app calculated them
/// itself, the customer could be shown one number and charged another.
class NewFinanceScreen extends StatefulWidget {
  const NewFinanceScreen({
    super.key,
    required this.customerId,
    required this.customerName,
  });

  final String customerId;
  final String customerName;

  @override
  State<NewFinanceScreen> createState() => _NewFinanceScreenState();
}

class _NewFinanceScreenState extends State<NewFinanceScreen> {
  final _formKey = GlobalKey<FormState>();
  final _imei = TextEditingController();
  final _model = TextEditingController();
  final _price = TextEditingController();
  final _down = TextEditingController();
  final _tenure = TextEditingController(text: '11');

  /// Created once for this finance, reused if the request has to be retried.
  final String _requestId = newRequestId('fin');

  Map<String, dynamic>? _quote;
  bool _busy = false;

  @override
  void dispose() {
    _imei.dispose();
    _model.dispose();
    _price.dispose();
    _down.dispose();
    _tenure.dispose();
    super.dispose();
  }

  Future<void> _getQuote() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      final quote = await session.api.post('/finance/quote', body: {
        'product_price': Money.toPaise(_price.text),
        'down_payment': Money.toPaise(_down.text),
        'tenure_months': int.parse(_tenure.text),
      }) as Map;
      if (!mounted) return;
      setState(() => _quote = Map<String, dynamic>.from(quote));
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _activate() async {
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      final created = await session.api.post(
        '/finance',
        idempotencyKey: _requestId,
        body: {
          'customer_id': widget.customerId,
          'imei': _imei.text.trim(),
          'model': _model.text.trim().isEmpty ? null : _model.text.trim(),
          'product_price': Money.toPaise(_price.text),
          'down_payment': Money.toPaise(_down.text),
          'tenure_months': int.parse(_tenure.text),
          'grace_days': 5,
        },
      ) as Map;
      if (!mounted) return;
      showOk(context,
          'Finance ${created['finance_id']} activated — 1 activation used');
      Navigator.of(context).pop(created['finance_id'].toString());
    } on ApiException catch (error) {
      if (mounted) {
        showError(context, error);
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_quote == null ? 'New finance' : 'Agreement'),
        leading: _quote == null
            ? null
            : IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () => setState(() => _quote = null),
              ),
      ),
      body: _quote == null ? _buildForm(context) : _buildAgreement(context),
    );
  }

  Widget _buildForm(BuildContext context) {
    return Form(
      key: _formKey,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: ListTile(
              leading: const Icon(Icons.person_outline),
              title: Text(widget.customerName),
              subtitle: Text(widget.customerId),
            ),
          ),
          const SizedBox(height: 20),
          Text('Device', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          TextFormField(
            controller: _imei,
            keyboardType: TextInputType.number,
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(15),
            ],
            decoration: const InputDecoration(
              labelText: 'IMEI',
              helperText: 'Dial *#06# on the handset to see it',
            ),
            validator: (value) {
              final imei = value?.trim() ?? '';
              if (imei.length != 15) return 'An IMEI is 15 digits';
              if (!isValidImei(imei)) {
                return 'That IMEI fails its checksum - check for a typo';
              }
              return null;
            },
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _model,
            textCapitalization: TextCapitalization.words,
            decoration: const InputDecoration(labelText: 'Model (optional)'),
          ),
          const SizedBox(height: 24),
          Text('Pricing', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          TextFormField(
            controller: _price,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(
                labelText: 'Product price', prefixText: '₹  '),
            validator: (value) {
              final paise = Money.toPaise(value ?? '');
              if (paise == null || paise <= 0) return 'Enter the price';
              return null;
            },
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _down,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(
                labelText: 'Down payment', prefixText: '₹  '),
            validator: (value) {
              final paise = Money.toPaise(value ?? '');
              if (paise == null) return 'Enter the down payment';
              final price = Money.toPaise(_price.text) ?? 0;
              if (paise >= price) {
                return 'Down payment must be less than the price';
              }
              return null;
            },
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _tenure,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: const InputDecoration(labelText: 'Tenure (months)'),
            validator: (value) {
              final months = int.tryParse(value ?? '');
              if (months == null || months < 1 || months > 60) {
                return 'Enter 1 to 60 months';
              }
              return null;
            },
          ),
          const SizedBox(height: 28),
          FilledButton(
            onPressed: _busy ? null : _getQuote,
            child: _busy
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Calculate EMI'),
          ),
        ],
      ),
    );
  }

  Widget _buildAgreement(BuildContext context) {
    final quote = _quote!;
    final schedule = List<Map<String, dynamic>>.from(
        (quote['schedule'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
    final scheme = Theme.of(context).colorScheme;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Finance terms',
                    style: Theme.of(context).textTheme.titleMedium),
                const Divider(height: 24),
                LabelledRow('Customer', widget.customerName),
                LabelledRow('IMEI', _imei.text.trim()),
                if (_model.text.trim().isNotEmpty)
                  LabelledRow('Model', _model.text.trim()),
                const Divider(height: 24),
                LabelledRow(
                    'Product price', Money.format(quote['product_price'] as int)),
                LabelledRow(
                    'Down payment', Money.format(quote['down_payment'] as int)),
                LabelledRow('Financed amount',
                    Money.format(quote['financed_amount'] as int)),
                LabelledRow('Tenure', '${quote['tenure_months']} months'),
                LabelledRow(
                  'Monthly EMI',
                  Money.format(quote['emi_amount'] as int),
                  valueStyle: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                if (quote['final_emi_amount'] != quote['emi_amount'])
                  LabelledRow('Final instalment',
                      Money.format(quote['final_emi_amount'] as int)),
                LabelledRow('First due date',
                    formatDate(quote['first_due_date']?.toString())),
                LabelledRow('Total payable',
                    Money.format(quote['total_payable'] as int)),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Card(
          color: scheme.surfaceContainerHighest,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.gavel, size: 18, color: scheme.onSurfaceVariant),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text('Read to the customer',
                          style: Theme.of(context).textTheme.titleSmall),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  'The instalments above, the late fee and the 5-day grace '
                  'period apply for the full tenure. The device is enrolled in '
                  'device management for the duration of the finance, as set '
                  'out in the terms the customer has consented to. Activating '
                  'this finance uses one activation from your balance.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),
        Text('Schedule preview', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        Card(
          child: Column(
            children: [
              for (var i = 0; i < schedule.length; i++) ...[
                if (i > 0) const Divider(height: 1),
                ListTile(
                  dense: true,
                  leading: CircleAvatar(
                    radius: 14,
                    child: Text('${schedule[i]['seq']}',
                        style: const TextStyle(fontSize: 11)),
                  ),
                  title: Text(Money.format(schedule[i]['amount_paise'] as int)),
                  trailing:
                      Text(formatDate(schedule[i]['due_date']?.toString())),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 24),
        // A plain button, not FilledButton.icon: an icon plus a label this long
        // overflows the row at 360dp. Centred text wraps instead.
        FilledButton(
          onPressed: _busy ? null : _activate,
          child: _busy
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Text(
                  'Customer agrees — activate finance',
                  textAlign: TextAlign.center,
                ),
        ),
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed: _busy ? null : () => setState(() => _quote = null),
          child: const Text('Go back and change'),
        ),
        const SizedBox(height: 32),
      ],
    );
  }
}
