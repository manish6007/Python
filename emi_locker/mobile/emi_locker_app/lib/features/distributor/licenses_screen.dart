import 'package:flutter/material.dart';

import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// Activation packs this distributor holds, plus redeeming a new key.
class LicensesScreen extends StatefulWidget {
  const LicensesScreen({super.key});

  @override
  State<LicensesScreen> createState() => _LicensesScreenState();
}

class _LicensesScreenState extends State<LicensesScreen> {
  final _viewKey = GlobalKey<AsyncViewState<Map<String, dynamic>>>();

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return Scaffold(
      body: AsyncView<Map<String, dynamic>>(
        key: _viewKey,
        load: () async => Map<String, dynamic>.from(
            await session.api.get('/distributor/licenses') as Map),
        builder: (context, data, reload) {
          final licences = List<Map<String, dynamic>>.from(
              (data['licenses'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
          if (licences.isEmpty) {
            return ListView(
              children: const [
                SizedBox(height: 100),
                EmptyState(
                  icon: Icons.key_off_outlined,
                  title: 'No activation packs yet',
                  subtitle:
                      'Buy a pack from head office, then redeem the key they '
                      'send you using the button below.',
                ),
              ],
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
            itemCount: licences.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (context, index) {
              final licence = licences[index];
              final consumed = licence['consumed'] as int;
              final quota = licence['quota'] as int;
              return Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(licence['plan_name'].toString(),
                                style: Theme.of(context)
                                    .textTheme
                                    .titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w600)),
                          ),
                          StatusChip(status: licence['status'].toString()),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${licence['id']} • ${licence['key_masked']}',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontFamily: 'monospace',
                            ),
                      ),
                      const Divider(height: 24),
                      LabelledRow('Activations in pack', '$quota'),
                      LabelledRow('Used directly by me', '$consumed'),
                      LabelledRow('Valid until',
                          formatDate(licence['valid_to']?.toString())),
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final redeemed = await showModalBottomSheet<bool>(
            context: context,
            isScrollControlled: true,
            builder: (_) => const _RedeemSheet(),
          );
          if (redeemed == true) _viewKey.currentState?.reload();
        },
        icon: const Icon(Icons.vpn_key),
        label: const Text('Redeem key'),
      ),
    );
  }
}

class _RedeemSheet extends StatefulWidget {
  const _RedeemSheet();

  @override
  State<_RedeemSheet> createState() => _RedeemSheetState();
}

class _RedeemSheetState extends State<_RedeemSheet> {
  final _key = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _key.dispose();
    super.dispose();
  }

  Future<void> _redeem() async {
    if (_key.text.trim().isEmpty) return;
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      final out = await session.api
          .post('/distributor/redeem', body: {'key': _key.text.trim()}) as Map;
      if (!mounted) return;
      final wallet = Map<String, dynamic>.from(out['wallet'] as Map);
      showOk(context,
          '${out['quota']} activations added — balance is now '
          '${wallet['available']}');
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
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Redeem an activation pack',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(
            'Enter the key head office sent you. A key can only be claimed once.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 20),
          TextField(
            controller: _key,
            autofocus: true,
            textCapitalization: TextCapitalization.characters,
            style: const TextStyle(fontFamily: 'monospace', letterSpacing: 1.5),
            decoration: const InputDecoration(
              labelText: 'Licence key',
              hintText: 'XXXXX-XXXXX-XXXXX-XXXXX',
            ),
            onSubmitted: (_) => _redeem(),
          ),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _busy ? null : _redeem,
            child: _busy
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Redeem'),
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}
