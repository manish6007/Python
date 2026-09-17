import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// Business settings, including the commission rates.
///
/// Rates start at zero and stay there until someone decides them. That is why
/// the commission screens say "no rate configured" rather than showing zero as
/// though it were an answer.
class AdminSettings extends StatefulWidget {
  const AdminSettings({super.key});

  @override
  State<AdminSettings> createState() => _AdminSettingsState();
}

class _AdminSettingsState extends State<AdminSettings> {
  final _viewKey = GlobalKey<AsyncViewState<Map<String, dynamic>>>();

  static const _moneyKeys = {
    'commission.distributor_per_activation_paise',
    'commission.retailer_per_activation_paise',
    'finance.default_late_fee_paise',
  };

  Future<void> _edit(String key, Map<String, dynamic> setting) async {
    final isMoney = _moneyKeys.contains(key);
    final current = setting['value'];
    final initial = isMoney
        ? Money.toRupeeString(current as int)
        : current.toString();

    final updated = await showDialog<String>(
      context: context,
      builder: (_) => _EditSettingDialog(
        settingKey: key,
        description: setting['description'].toString(),
        initial: initial,
        isMoney: isMoney,
        isNumber: current is int,
      ),
    );
    if (updated == null || !mounted) return;

    final session = SessionScope.of(context);
    try {
      final value = current is int
          ? (isMoney ? Money.toPaise(updated) : int.tryParse(updated.trim()))
          : updated;
      await session.api.put('/admin/settings', body: {'key': key, 'value': value});
      if (!mounted) return;
      showOk(context, 'Saved');
      _viewKey.currentState?.reload();
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    }
  }

  String _display(String key, Map<String, dynamic> setting) {
    final value = setting['value'];
    if (_moneyKeys.contains(key)) return Money.format(value as int);
    if (key.endsWith('_bp')) return '${(value as int) / 100}%';
    if (value is String && value.isEmpty) return 'Not set';
    return value.toString();
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      key: _viewKey,
      load: () async =>
          Map<String, dynamic>.from(await session.api.get('/admin/settings') as Map),
      builder: (context, data, reload) {
        final settings = Map<String, dynamic>.from(data['settings'] as Map);
        final groups = <String, List<String>>{};
        for (final key in settings.keys) {
          groups.putIfAbsent(key.split('.').first, () => []).add(key);
        }
        const groupTitles = {
          'commission': 'Commission',
          'finance': 'Finance defaults',
          'business': 'Business details',
        };

        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            PageBody(
              maxWidth: 780,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final group in ['commission', 'finance', 'business'])
                    if (groups.containsKey(group)) ...[
                      Text(groupTitles[group] ?? group,
                          style: Theme.of(context).textTheme.titleMedium),
                      const SizedBox(height: 8),
                      Card(
                        child: Column(
                          children: [
                            for (var i = 0; i < groups[group]!.length; i++) ...[
                              if (i > 0) const Divider(height: 1),
                              Builder(builder: (context) {
                                final key = groups[group]![i];
                                final setting =
                                    Map<String, dynamic>.from(settings[key] as Map);
                                return ListTile(
                                  title: Text(_display(key, setting),
                                      style: const TextStyle(
                                          fontWeight: FontWeight.w700)),
                                  subtitle: Text(setting['description'].toString()),
                                  trailing: IconButton(
                                    tooltip: 'Change',
                                    icon: const Icon(Icons.edit_outlined, size: 18),
                                    onPressed: () => _edit(key, setting),
                                  ),
                                );
                              }),
                            ],
                          ],
                        ),
                      ),
                      const SizedBox(height: 24),
                    ],
                  Card(
                    color: Theme.of(context).colorScheme.surfaceContainerHighest,
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(
                        'Every change here is written to the audit log with who '
                        'made it and what it was before.',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
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

class _EditSettingDialog extends StatefulWidget {
  const _EditSettingDialog({
    required this.settingKey,
    required this.description,
    required this.initial,
    required this.isMoney,
    required this.isNumber,
  });

  final String settingKey;
  final String description;
  final String initial;
  final bool isMoney;
  final bool isNumber;

  @override
  State<_EditSettingDialog> createState() => _EditSettingDialogState();
}

class _EditSettingDialogState extends State<_EditSettingDialog> {
  late final TextEditingController _value =
      TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _value.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isBasisPoints = widget.settingKey.endsWith('_bp');
    return AlertDialog(
      title: const Text('Change setting'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.description),
            const SizedBox(height: 16),
            TextField(
              controller: _value,
              autofocus: true,
              keyboardType: widget.isNumber
                  ? const TextInputType.numberWithOptions(decimal: true)
                  : TextInputType.text,
              decoration: InputDecoration(
                labelText: widget.isMoney ? 'Amount' : 'Value',
                prefixText: widget.isMoney ? '₹  ' : null,
                helperText: isBasisPoints
                    ? 'In basis points: 250 means 2.5%'
                    : null,
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel')),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
          onPressed: () => Navigator.of(context).pop(_value.text),
          child: const Text('Save'),
        ),
      ],
    );
  }
}
