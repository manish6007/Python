import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/adaptive.dart';
import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// Licence plans and issued keys - the stock side of the business.
class AdminLicences extends StatefulWidget {
  const AdminLicences({super.key});

  @override
  State<AdminLicences> createState() => _AdminLicencesState();
}

class _AdminLicencesState extends State<AdminLicences> {
  final _viewKey = GlobalKey<AsyncViewState<List<dynamic>>>();

  Future<void> _issue(List<Map<String, dynamic>> plans) async {
    final issued = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _IssueLicenceDialog(plans: plans),
    );
    if (issued == null || !mounted) return;
    // The raw key exists in exactly one place: this dialog. It is stored
    // hashed, so if it is not copied now it can never be recovered.
    await showDialog<void>(
      context: context,
      builder: (_) => _KeyDialog(result: issued),
    );
    _viewKey.currentState?.reload();
  }

  Future<void> _setStatus(Map<String, dynamic> licence) async {
    final suspend = licence['status'] == 'ACTIVE';
    final session = SessionScope.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(suspend ? 'Suspend licence?' : 'Reactivate licence?'),
        content: Text(
          suspend
              ? 'The holder will not be able to activate any more devices. '
                  'Existing finance accounts are unaffected.'
              : 'The holder can activate devices again.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel')),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(suspend ? 'Suspend' : 'Reactivate'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await session.api.post('/admin/licenses/${licence['id']}/status', body: {
        'status': suspend ? 'SUSPENDED' : 'ACTIVE',
        'reason': suspend ? 'suspended from admin panel' : 'reactivated from admin panel',
      });
      if (!mounted) return;
      showOk(context, suspend ? 'Licence suspended' : 'Licence reactivated');
      _viewKey.currentState?.reload();
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    }
  }

  Future<void> _addPlan() async {
    final added = await showDialog<bool>(
      context: context,
      builder: (_) => const _AddPlanDialog(),
    );
    if (added == true) _viewKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<List<dynamic>>(
      key: _viewKey,
      load: () => Future.wait([
        session.api.get('/admin/plans'),
        session.api.get('/admin/licenses'),
      ]),
      builder: (context, data, reload) {
        final plans = List<Map<String, dynamic>>.from(
            ((data[0] as Map)['plans'] as List)
                .map((e) => Map<String, dynamic>.from(e as Map)));
        final licences = List<Map<String, dynamic>>.from(
            ((data[1] as Map)['licenses'] as List)
                .map((e) => Map<String, dynamic>.from(e as Map)));

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            PageBody(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text('Plans',
                            style: Theme.of(context).textTheme.titleMedium),
                      ),
                      OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                            minimumSize: const Size(0, 42)),
                        onPressed: _addPlan,
                        icon: const Icon(Icons.add, size: 18),
                        label: const Text('New plan'),
                      ),
                      const SizedBox(width: 10),
                      FilledButton.icon(
                        style: FilledButton.styleFrom(
                            minimumSize: const Size(0, 42)),
                        onPressed: plans.isEmpty ? null : () => _issue(plans),
                        icon: const Icon(Icons.vpn_key, size: 18),
                        label: const Text('Issue licence'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  RecordTable(
                    emptyMessage: 'No plans yet',
                    columns: const [
                      'Plan',
                      'Activations',
                      'Price',
                      'Validity',
                      'Issued'
                    ],
                    rows: [
                      for (final plan in plans)
                        [
                          Text(plan['name'].toString()),
                          Text('${plan['quota']}'),
                          Text(Money.format(plan['price_paise'] as int)),
                          Text('${plan['validity_days']} days'),
                          Text('${plan['issued']}'),
                        ],
                    ],
                  ),
                  const SizedBox(height: 28),
                  Text('Issued licences',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 12),
                  RecordTable(
                    emptyMessage: 'No licences issued yet',
                    columns: const [
                      'Licence',
                      'Plan',
                      'Key',
                      'Owner',
                      'Quota',
                      'Used',
                      'Expires',
                      'Status',
                      ''
                    ],
                    rows: [
                      for (final licence in licences)
                        [
                          Text(licence['id'].toString()),
                          Text(licence['plan_name'].toString()),
                          Text(licence['key_masked'].toString(),
                              style: const TextStyle(fontFamily: 'monospace')),
                          Text(licence['owner_name']?.toString() ??
                              'Unclaimed (${licence['owner_type']})'),
                          Text('${licence['quota']}'),
                          Text('${licence['consumed']}'),
                          Text(formatDate(licence['valid_to']?.toString())),
                          StatusChip(status: licence['status'].toString(), dense: true),
                          licence['status'] == 'REVOKED'
                              ? const SizedBox.shrink()
                              : IconButton(
                                  tooltip: licence['status'] == 'ACTIVE'
                                      ? 'Suspend'
                                      : 'Reactivate',
                                  icon: Icon(
                                      licence['status'] == 'ACTIVE'
                                          ? Icons.block
                                          : Icons.play_circle_outline,
                                      size: 18),
                                  onPressed: () => _setStatus(licence),
                                ),
                        ],
                    ],
                  ),
                  const SizedBox(height: 40),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

class _AddPlanDialog extends StatefulWidget {
  const _AddPlanDialog();

  @override
  State<_AddPlanDialog> createState() => _AddPlanDialogState();
}

class _AddPlanDialogState extends State<_AddPlanDialog> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _quota = TextEditingController(text: '100');
  final _price = TextEditingController(text: '25000');
  final _validity = TextEditingController(text: '365');
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _quota.dispose();
    _price.dispose();
    _validity.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      await session.api.post('/admin/plans', body: {
        'name': _name.text.trim().toUpperCase(),
        'quota': int.parse(_quota.text.trim()),
        'price_paise': Money.toPaise(_price.text),
        'validity_days': int.parse(_validity.text.trim()),
      });
      if (!mounted) return;
      showOk(context, 'Plan created');
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
    return AlertDialog(
      title: const Text('New licence plan'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(
                    labelText: 'Plan name', hintText: 'BUSINESS'),
                validator: (v) =>
                    (v == null || v.trim().length < 2) ? 'Enter a name' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _quota,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(labelText: 'Activations included'),
                validator: (v) => (int.tryParse(v ?? '') ?? 0) < 1
                    ? 'Enter a number above zero'
                    : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _price,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration:
                    const InputDecoration(labelText: 'Price', prefixText: '₹  '),
                validator: (v) =>
                    Money.toPaise(v ?? '') == null ? 'Enter a price' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _validity,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(labelText: 'Validity in days'),
                validator: (v) => (int.tryParse(v ?? '') ?? 0) < 1
                    ? 'Enter a number of days'
                    : null,
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
            onPressed: _busy ? null : () => Navigator.of(context).pop(false),
            child: const Text('Cancel')),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
          onPressed: _busy ? null : _save,
          child: const Text('Create'),
        ),
      ],
    );
  }
}

class _IssueLicenceDialog extends StatefulWidget {
  const _IssueLicenceDialog({required this.plans});

  final List<Map<String, dynamic>> plans;

  @override
  State<_IssueLicenceDialog> createState() => _IssueLicenceDialogState();
}

class _IssueLicenceDialogState extends State<_IssueLicenceDialog> {
  String? _planId;
  String _ownerType = 'DISTRIBUTOR';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _planId = widget.plans.first['id'].toString();
  }

  Future<void> _issue() async {
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      final out = await session.api.post('/admin/licenses/generate', body: {
        'plan_id': _planId,
        'owner_type': _ownerType,
      }) as Map;
      if (!mounted) return;
      Navigator.of(context).pop(Map<String, dynamic>.from(out));
    } on ApiException catch (error) {
      if (mounted) {
        showError(context, error);
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Issue a licence key'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DropdownButtonFormField<String>(
              initialValue: _planId,
              // Without isExpanded a long plan label overflows the field
              // instead of being ellipsised.
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Plan'),
              items: [
                for (final plan in widget.plans)
                  DropdownMenuItem(
                    value: plan['id'].toString(),
                    child: Text(
                      '${plan['name']} — ${plan['quota']} activations',
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: (value) => setState(() => _planId = value),
            ),
            const SizedBox(height: 16),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'DISTRIBUTOR', label: Text('Distributor')),
                ButtonSegment(value: 'RETAILER', label: Text('Retailer')),
              ],
              selected: {_ownerType},
              onSelectionChanged: (s) => setState(() => _ownerType = s.first),
            ),
            const SizedBox(height: 14),
            Text(
              'The key is generated unclaimed. Send it to the buyer, who '
              'redeems it in their own app.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
            onPressed: _busy ? null : () => Navigator.of(context).pop(),
            child: const Text('Cancel')),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
          onPressed: _busy ? null : _issue,
          child: const Text('Issue'),
        ),
      ],
    );
  }
}

class _KeyDialog extends StatelessWidget {
  const _KeyDialog({required this.result});

  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final key = result['key'].toString();
    return AlertDialog(
      title: const Text('Licence issued'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${result['license_id']} • ${result['quota']} activations '
                '• valid to ${formatDate(result['valid_to']?.toString())}'),
            const SizedBox(height: 16),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(12),
              ),
              child: SelectableText(
                key,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 20,
                  letterSpacing: 2,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Icon(Icons.warning_amber_outlined,
                    size: 18, color: Theme.of(context).colorScheme.error),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Copy this now. Only a hash is stored, so it cannot be '
                    'shown again.',
                    style: TextStyle(
                        fontSize: 12, color: Theme.of(context).colorScheme.error),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        OutlinedButton.icon(
          style: OutlinedButton.styleFrom(minimumSize: const Size(0, 40)),
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: key));
            if (context.mounted) showOk(context, 'Key copied');
          },
          icon: const Icon(Icons.copy, size: 18),
          label: const Text('Copy key'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Done'),
        ),
      ],
    );
  }
}
