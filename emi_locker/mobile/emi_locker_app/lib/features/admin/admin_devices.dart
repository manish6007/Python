import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../core/api_client.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import 'admin_finances.dart' show StatusFilter;

const deviceStatuses = [
  '',
  'ACTIVE',
  'PAYMENT_DUE',
  'GRACE_PERIOD',
  'OVERDUE',
  'RESTRICTED',
  'RESTORED',
  'COMPLETED',
];

/// Enrolled devices and the authorised actions raised against them.
///
/// Worth being clear about what the buttons here do: they queue a request,
/// which a second admin approves, which is then handed to a device-management
/// provider. With no provider configured - the default - nothing is sent, and
/// the result says so. See FEASIBILITY.md §3.1.
class AdminDevices extends StatefulWidget {
  const AdminDevices({super.key});

  @override
  State<AdminDevices> createState() => _AdminDevicesState();
}

class _AdminDevicesState extends State<AdminDevices> {
  final _viewKey = GlobalKey<AsyncViewState<Map<String, dynamic>>>();
  String _status = '';

  Future<void> _requestRestriction(Map<String, dynamic> device) async {
    final session = SessionScope.of(context);
    final reason = await showDialog<String>(
      context: context,
      builder: (_) => const _ReasonPrompt(
        title: 'Request device restriction',
        message:
            'This raises a request for another admin to approve. Nothing is '
            'sent to the device until a provider is configured.',
      ),
    );
    if (reason == null || !mounted) return;
    try {
      final out = await session.api.post('/device-actions', body: {
        'device_id': device['id'],
        'command': 'RESTRICT',
        'reason': reason,
      }) as Map;
      if (!mounted) return;
      showOk(context, 'Request ${out['command_id']} is ${out['status']}');
      _viewKey.currentState?.reload();
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    }
  }

  Future<void> _showCommands(Map<String, dynamic> device) async {
    final session = SessionScope.of(context);
    try {
      final out = await session.api
          .get('/devices/${device['id']}/commands') as Map;
      final commands = List<Map<String, dynamic>>.from(
          (out['commands'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (_) => _CommandsDialog(
          imei: device['imei'].toString(),
          commands: commands,
          onApprove: (commandId) async {
            try {
              final result = await session.api
                  .post('/device-actions/$commandId/approve') as Map;
              final dispatch = Map<String, dynamic>.from(result['dispatch'] as Map);
              if (!mounted) return;
              Navigator.of(context).pop();
              showOk(
                context,
                'Approved. Dispatch: ${dispatch['status']}'
                '${dispatch['detail'] == null ? '' : ' — ${dispatch['detail']}'}',
              );
              _viewKey.currentState?.reload();
            } on ApiException catch (error) {
              if (mounted) showError(context, error);
            }
          },
        ),
      );
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        PageBody(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Card(
                color: Theme.of(context).colorScheme.tertiaryContainer,
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    children: [
                      Icon(Icons.info_outline,
                          size: 18,
                          color: Theme.of(context).colorScheme.onTertiaryContainer),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Device actions are recorded and audited here. No '
                          'handset is actually restricted until an authorised '
                          'device-management provider is connected.',
                          style: TextStyle(
                            fontSize: 12,
                            color:
                                Theme.of(context).colorScheme.onTertiaryContainer,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              StatusFilter(
                statuses: deviceStatuses,
                selected: _status,
                onChanged: (value) {
                  setState(() => _status = value);
                  _viewKey.currentState?.reload();
                },
              ),
              const SizedBox(height: 16),
              SizedBox(
                height: MediaQuery.sizeOf(context).height * 0.62,
                child: AsyncView<Map<String, dynamic>>(
                  key: _viewKey,
                  load: () async => Map<String, dynamic>.from(
                    await session.api
                        .get('/admin/devices', query: {'status': _status}) as Map,
                  ),
                  builder: (context, data, reload) {
                    final devices = List<Map<String, dynamic>>.from(
                        (data['devices'] as List)
                            .map((e) => Map<String, dynamic>.from(e as Map)));
                    return ListView(
                      children: [
                        RecordTable(
                          emptyMessage: 'No devices match this filter',
                          columns: const [
                            'IMEI',
                            'Model',
                            'Customer',
                            'Finance',
                            'Status',
                            'Enrolled',
                            ''
                          ],
                          rows: [
                            for (final device in devices)
                              [
                                Text(device['imei'].toString()),
                                Text(device['model']?.toString() ?? '-'),
                                Text(device['customer_name'].toString()),
                                Text(device['finance_id']?.toString() ?? '-'),
                                StatusChip(status: device['status'].toString()),
                                Text(formatDate(device['created_at']
                                    ?.toString()
                                    .split('T')
                                    .first)),
                                Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    IconButton(
                                      tooltip: 'Action history',
                                      icon: const Icon(Icons.history, size: 18),
                                      onPressed: () => _showCommands(device),
                                    ),
                                    IconButton(
                                      tooltip: 'Request restriction',
                                      icon: const Icon(Icons.lock_outline, size: 18),
                                      onPressed: () => _requestRestriction(device),
                                    ),
                                  ],
                                ),
                              ],
                          ],
                        ),
                      ],
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _CommandsDialog extends StatelessWidget {
  const _CommandsDialog({
    required this.imei,
    required this.commands,
    required this.onApprove,
  });

  final String imei;
  final List<Map<String, dynamic>> commands;
  final Future<void> Function(String commandId) onApprove;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Device $imei'),
      content: SizedBox(
        width: 560,
        child: commands.isEmpty
            ? const Padding(
                padding: EdgeInsets.all(24),
                child: Text('No actions have been raised for this device.'),
              )
            : Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final command in commands)
                    ListTile(
                      title: Text(
                          '${command['command']} • ${command['status']}'),
                      subtitle: Text(
                        '${command['reason']}\n'
                        'Requested ${formatDateTime(command['created_at']?.toString())}',
                      ),
                      isThreeLine: true,
                      trailing: command['status'] == 'PENDING_APPROVAL'
                          ? FilledButton(
                              style: FilledButton.styleFrom(
                                  minimumSize: const Size(0, 36)),
                              onPressed: () =>
                                  onApprove(command['id'].toString()),
                              child: const Text('Approve'),
                            )
                          : null,
                    ),
                ],
              ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }
}

class _ReasonPrompt extends StatefulWidget {
  const _ReasonPrompt({required this.title, required this.message});

  final String title;
  final String message;

  @override
  State<_ReasonPrompt> createState() => _ReasonPromptState();
}

class _ReasonPromptState extends State<_ReasonPrompt> {
  final _reason = TextEditingController();

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 440,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.message),
            const SizedBox(height: 16),
            TextField(
              controller: _reason,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Reason'),
              onChanged: (_) => setState(() {}),
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
          onPressed: _reason.text.trim().length < 3
              ? null
              : () => Navigator.of(context).pop(_reason.text.trim()),
          child: const Text('Raise request'),
        ),
      ],
    );
  }
}
