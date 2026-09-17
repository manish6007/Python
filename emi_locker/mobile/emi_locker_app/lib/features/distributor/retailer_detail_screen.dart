import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/request_id.dart';
import '../../core/widgets.dart';
import '../../main.dart';

class RetailerDetailScreen extends StatelessWidget {
  const RetailerDetailScreen({
    super.key,
    required this.retailerId,
    required this.retailerName,
  });

  final String retailerId;
  final String retailerName;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(retailerName)),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => Map<String, dynamic>.from(
            await session.api.get('/distributor/retailers/$retailerId') as Map),
        builder: (context, data, reload) {
          final wallet = Map<String, dynamic>.from(data['wallet'] as Map);
          final finances = List<Map<String, dynamic>>.from(
              (data['finances'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
          final allocations = List<Map<String, dynamic>>.from(
              (data['allocations'] as List)
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
                      Text('Activation balance',
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 12),
                      LabelledRow('Allocated in total', '${wallet['total']}'),
                      LabelledRow('Used', '${wallet['used']}'),
                      LabelledRow('Available now', '${wallet['available']}'),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: () async {
                  final allocated = await showModalBottomSheet<bool>(
                    context: context,
                    isScrollControlled: true,
                    builder: (_) => _AllocateSheet(
                      retailerId: retailerId,
                      retailerName: retailerName,
                    ),
                  );
                  if (allocated == true) await reload();
                },
                icon: const Icon(Icons.add),
                label: const Text('Allocate activations'),
              ),
              const SizedBox(height: 24),
              Text('Recent allocations',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              if (allocations.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(24),
                    child: Center(child: Text('Nothing allocated yet')),
                  ),
                )
              else
                Card(
                  child: Column(
                    children: [
                      for (var i = 0; i < allocations.length; i++) ...[
                        if (i > 0) const Divider(height: 1),
                        ListTile(
                          dense: true,
                          leading: const Icon(Icons.arrow_downward, size: 18),
                          title: Text('${allocations[i]['quota']} activations'),
                          subtitle: Text(formatDateTime(
                              allocations[i]['created_at']?.toString())),
                        ),
                      ],
                    ],
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
                      title: Text(finance['customer_name'].toString(),
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                      subtitle: Text(
                        '${Money.format(finance['principal'] as int)} over '
                        '${finance['tenure_months']} months • '
                        '${Money.format(finance['outstanding_paise'] as int)} due',
                      ),
                      trailing: StatusChip(status: finance['status'].toString()),
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

/// Allocating stock down to a retailer.
///
/// The idempotency key is made once when the sheet opens, so a double tap or a
/// retry on a bad connection cannot hand out the quota twice.
class _AllocateSheet extends StatefulWidget {
  const _AllocateSheet({required this.retailerId, required this.retailerName});

  final String retailerId;
  final String retailerName;

  @override
  State<_AllocateSheet> createState() => _AllocateSheetState();
}

class _AllocateSheetState extends State<_AllocateSheet> {
  final _quota = TextEditingController(text: '25');
  final _formKey = GlobalKey<FormState>();
  final String _requestId = newRequestId('alloc');
  bool _busy = false;

  @override
  void dispose() {
    _quota.dispose();
    super.dispose();
  }

  Future<void> _allocate() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      final out = await session.api.post(
        '/distributor/allocate',
        idempotencyKey: _requestId,
        body: {
          'to_owner': widget.retailerId,
          'quota': int.parse(_quota.text.trim()),
        },
      ) as Map;
      if (!mounted) return;
      final wallet = Map<String, dynamic>.from(out['wallet'] as Map);
      showOk(context,
          'Allocated ${out['quota']} — ${widget.retailerName} now has '
          '${wallet['available']} available');
      Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) {
        showError(context, error);
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
      ),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Allocate to ${widget.retailerName}',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text(
              'Taken from your own balance and added to theirs.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
            const SizedBox(height: 20),
            TextFormField(
              controller: _quota,
              autofocus: true,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: const InputDecoration(labelText: 'Activations'),
              validator: (value) {
                final quota = int.tryParse(value?.trim() ?? '');
                if (quota == null || quota < 1) return 'Enter a number above zero';
                return null;
              },
            ),
            const SizedBox(height: 20),
            FilledButton(
              onPressed: _busy ? null : _allocate,
              child: _busy
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Allocate'),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}
