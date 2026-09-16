import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import '../customer/finance_detail.dart';
import 'new_finance_screen.dart';

class CustomerDetailScreen extends StatelessWidget {
  const CustomerDetailScreen({super.key, required this.customerId});

  final String customerId;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Customer')),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => Map<String, dynamic>.from(
            await session.api.get('/retailer/customers/$customerId') as Map),
        builder: (context, customer, reload) {
          final missing = List<String>.from(
              (customer['missing_consents'] as List).map((e) => e.toString()));
          final finances = List<Map<String, dynamic>>.from(
              (customer['finances'] as List)
                  .map((e) => Map<String, dynamic>.from(e as Map)));
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          CircleAvatar(
                            radius: 24,
                            child: Text(customer['name']
                                .toString()
                                .characters
                                .first
                                .toUpperCase()),
                          ),
                          const SizedBox(width: 14),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(customer['name'].toString(),
                                    style: Theme.of(context)
                                        .textTheme
                                        .titleMedium
                                        ?.copyWith(fontWeight: FontWeight.w600)),
                                Text('+91 ${customer['mobile']}'),
                              ],
                            ),
                          ),
                        ],
                      ),
                      const Divider(height: 28),
                      LabelledRow('Customer ID', customer['id'].toString()),
                      LabelledRow(
                          'Address', customer['address']?.toString() ?? '-'),
                      LabelledRow('KYC', customer['kyc_status'].toString()),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              _ConsentCard(
                customerId: customerId,
                required: List<String>.from((customer['required_consents'] as List)
                    .map((e) => e.toString())),
                missing: missing,
                onChanged: reload,
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: missing.isEmpty
                    ? () async {
                        final created = await Navigator.of(context).push<String>(
                          MaterialPageRoute(
                            builder: (_) => NewFinanceScreen(
                              customerId: customerId,
                              customerName: customer['name'].toString(),
                            ),
                          ),
                        );
                        if (created != null) await reload();
                      }
                    : null,
                icon: const Icon(Icons.add_card),
                label: const Text('New finance'),
              ),
              if (missing.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Record all consents before starting a finance.',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.error,
                        ),
                  ),
                ),
              const SizedBox(height: 24),
              Text('Finance accounts',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (finances.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Center(child: Text('No finance yet')),
                  ),
                )
              else
                for (final finance in finances) ...[
                  Card(
                    child: ListTile(
                      title: Text(Money.format(finance['principal'] as int),
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                      subtitle: Text(
                        '${finance['tenure_months']} months • '
                        '${Money.format(finance['emi_amount'] as int)} / month',
                      ),
                      trailing: StatusChip(status: finance['status'].toString()),
                      onTap: () => Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) => FinanceDetailScreen(
                          financeId: finance['id'].toString(),
                          allowPay: false,
                        ),
                      )),
                    ),
                  ),
                  const SizedBox(height: 10),
                ],
              const SizedBox(height: 32),
            ],
          );
        },
      ),
    );
  }
}

/// Consent capture.
///
/// Three consents are required before a finance can be activated, and
/// device-management consent is one of them. The backend refuses the finance
/// otherwise, so this is not a formality the app can skip.
class _ConsentCard extends StatefulWidget {
  const _ConsentCard({
    required this.customerId,
    required this.required,
    required this.missing,
    required this.onChanged,
  });

  final String customerId;
  final List<String> required;
  final List<String> missing;
  final Future<void> Function() onChanged;

  @override
  State<_ConsentCard> createState() => _ConsentCardState();
}

class _ConsentCardState extends State<_ConsentCard> {
  String? _busy;

  static const _labels = {
    'TERMS': 'Terms & conditions',
    'PRIVACY': 'Privacy policy',
    'DEVICE_MANAGEMENT': 'Device management terms',
  };

  Future<void> _record(String type) async {
    setState(() => _busy = type);
    final session = SessionScope.of(context);
    try {
      await session.api.post(
        '/retailer/customers/${widget.customerId}/consents',
        body: {'consent_type': type, 'doc_version': 'v1', 'channel': 'APP'},
      );
      await widget.onChanged();
      if (mounted) showOk(context, 'Consent recorded');
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => _busy = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Consent', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              'Read each document to the customer and record their agreement.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
            const SizedBox(height: 8),
            for (final type in widget.required)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: !widget.missing.contains(type),
                onChanged: widget.missing.contains(type) && _busy == null
                    ? (_) => _record(type)
                    : null,
                title: Text(_labels[type] ?? type),
                subtitle: _busy == type ? const Text('Recording…') : null,
              ),
          ],
        ),
      ),
    );
  }
}
