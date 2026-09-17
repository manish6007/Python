import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/adaptive.dart';
import '../../core/api_client.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// Distributors and the retailers under them, with the actions that change the
/// shape of the network: add an account, suspend one.
class AdminNetwork extends StatefulWidget {
  const AdminNetwork({super.key});

  @override
  State<AdminNetwork> createState() => _AdminNetworkState();
}

class _AdminNetworkState extends State<AdminNetwork> {
  final _viewKey = GlobalKey<AsyncViewState<Map<String, dynamic>>>();

  Future<void> _addUser(List<Map<String, dynamic>> distributors) async {
    final added = await showDialog<bool>(
      context: context,
      builder: (_) => _AddUserDialog(distributors: distributors),
    );
    if (added == true) _viewKey.currentState?.reload();
  }

  Future<void> _setStatus(Map<String, dynamic> user) async {
    final suspend = user['status'] == 'ACTIVE';
    final reason = await showDialog<String>(
      context: context,
      builder: (_) => _ReasonDialog(
        title: suspend ? 'Suspend ${user['name']}' : 'Reactivate ${user['name']}',
        message: suspend
            ? 'They will be signed out immediately and cannot create new '
                'finance. Existing records are untouched.'
            : 'They will be able to sign in and trade again.',
        actionLabel: suspend ? 'Suspend' : 'Reactivate',
      ),
    );
    if (reason == null || !mounted) return;
    final session = SessionScope.of(context);
    try {
      await session.api.post('/admin/users/${user['id']}/status', body: {
        'status': suspend ? 'SUSPENDED' : 'ACTIVE',
        'reason': reason,
      });
      if (!mounted) return;
      showOk(context, suspend ? 'Account suspended' : 'Account reactivated');
      _viewKey.currentState?.reload();
    } on ApiException catch (error) {
      if (mounted) showError(context, error);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      key: _viewKey,
      load: () async =>
          Map<String, dynamic>.from(await session.api.get('/admin/network') as Map),
      builder: (context, data, reload) {
        final distributors = List<Map<String, dynamic>>.from(
            (data['distributors'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        final unassigned = List<Map<String, dynamic>>.from(
            (data['unassigned_retailers'] as List)
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
                        child: Text(
                          '${distributors.length} distributor'
                          '${distributors.length == 1 ? '' : 's'}',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ),
                      FilledButton.icon(
                        style: FilledButton.styleFrom(
                            minimumSize: const Size(0, 42)),
                        onPressed: () => _addUser(distributors),
                        icon: const Icon(Icons.person_add, size: 18),
                        label: const Text('Add account'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  for (final distributor in distributors) ...[
                    _DistributorCard(
                      distributor: distributor,
                      onToggleStatus: _setStatus,
                    ),
                    const SizedBox(height: 14),
                  ],
                  if (unassigned.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Text('Retailers with no distributor',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Card(
                      child: Column(
                        children: [
                          for (final retailer in unassigned)
                            _RetailerTile(
                                retailer: retailer, onToggleStatus: _setStatus),
                        ],
                      ),
                    ),
                  ],
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

class _DistributorCard extends StatelessWidget {
  const _DistributorCard({required this.distributor, required this.onToggleStatus});

  final Map<String, dynamic> distributor;
  final Future<void> Function(Map<String, dynamic>) onToggleStatus;

  @override
  Widget build(BuildContext context) {
    final retailers = List<Map<String, dynamic>>.from(
        (distributor['retailers'] as List)
            .map((e) => Map<String, dynamic>.from(e as Map)));
    return Card(
      child: Column(
        children: [
          ListTile(
            leading: const CircleAvatar(child: Icon(Icons.account_tree_outlined)),
            title: Row(
              children: [
                Flexible(
                  child: Text(distributor['name'].toString(),
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                ),
                if (distributor['status'] != 'ACTIVE') ...[
                  const SizedBox(width: 8),
                  StatusChip(status: distributor['status'].toString(), dense: true),
                ],
              ],
            ),
            subtitle: Text(
              '+91 ${distributor['mobile'] ?? '-'} • '
              '${distributor['available_quota']} of ${distributor['total_quota']} '
              'activations free • ${retailers.length} retailer'
              '${retailers.length == 1 ? '' : 's'}',
            ),
            trailing: IconButton(
              tooltip: distributor['status'] == 'ACTIVE' ? 'Suspend' : 'Reactivate',
              icon: Icon(distributor['status'] == 'ACTIVE'
                  ? Icons.block
                  : Icons.play_circle_outline),
              onPressed: () => onToggleStatus(distributor),
            ),
          ),
          if (retailers.isNotEmpty) const Divider(height: 1),
          for (final retailer in retailers)
            _RetailerTile(retailer: retailer, onToggleStatus: onToggleStatus),
        ],
      ),
    );
  }
}

class _RetailerTile extends StatelessWidget {
  const _RetailerTile({required this.retailer, required this.onToggleStatus});

  final Map<String, dynamic> retailer;
  final Future<void> Function(Map<String, dynamic>) onToggleStatus;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: const EdgeInsets.only(left: 64, right: 8),
      leading: const Icon(Icons.storefront_outlined, size: 20),
      title: Row(
        children: [
          Flexible(child: Text(retailer['name'].toString())),
          if (retailer['status'] != 'ACTIVE') ...[
            const SizedBox(width: 8),
            StatusChip(status: retailer['status'].toString(), dense: true),
          ],
        ],
      ),
      subtitle: Text(
        '+91 ${retailer['mobile'] ?? '-'} • '
        '${retailer['available_quota']} of ${retailer['total_quota']} free',
      ),
      trailing: IconButton(
        tooltip: retailer['status'] == 'ACTIVE' ? 'Suspend' : 'Reactivate',
        icon: Icon(retailer['status'] == 'ACTIVE'
            ? Icons.block
            : Icons.play_circle_outline),
        onPressed: () => onToggleStatus(retailer),
      ),
    );
  }
}

class _AddUserDialog extends StatefulWidget {
  const _AddUserDialog({required this.distributors});

  final List<Map<String, dynamic>> distributors;

  @override
  State<_AddUserDialog> createState() => _AddUserDialogState();
}

class _AddUserDialogState extends State<_AddUserDialog> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _mobile = TextEditingController();
  String _role = 'RETAILER';
  String? _parentId;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _mobile.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    if (_role == 'RETAILER' && _parentId == null) {
      showError(context,
          ApiException('LOCAL', 'Choose which distributor this retailer sits under'));
      return;
    }
    setState(() => _busy = true);
    final session = SessionScope.of(context);
    try {
      await session.api.post('/admin/users', body: {
        'role': _role,
        'name': _name.text.trim(),
        'mobile': _mobile.text.trim(),
        'parent_id': _role == 'RETAILER' ? _parentId : null,
      });
      if (!mounted) return;
      showOk(context, '$_role created');
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
      title: const Text('Add an account'),
      content: SizedBox(
        width: 420,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'DISTRIBUTOR', label: Text('Distributor')),
                  ButtonSegment(value: 'RETAILER', label: Text('Retailer')),
                ],
                selected: {_role},
                onSelectionChanged: (s) => setState(() => _role = s.first),
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _name,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(labelText: 'Business name'),
                validator: (v) =>
                    (v == null || v.trim().length < 2) ? 'Enter a name' : null,
              ),
              const SizedBox(height: 14),
              TextFormField(
                controller: _mobile,
                keyboardType: TextInputType.phone,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(10),
                ],
                decoration: const InputDecoration(
                  labelText: 'Mobile number',
                  prefixText: '+91  ',
                  helperText: 'They sign in with this number',
                ),
                validator: (v) =>
                    (v == null || v.trim().length != 10) ? 'Enter 10 digits' : null,
              ),
              if (_role == 'RETAILER') ...[
                const SizedBox(height: 14),
                DropdownButtonFormField<String>(
                  initialValue: _parentId,
                  decoration: const InputDecoration(labelText: 'Under distributor'),
                  items: [
                    for (final distributor in widget.distributors)
                      DropdownMenuItem(
                        value: distributor['id'].toString(),
                        child: Text(distributor['name'].toString()),
                      ),
                  ],
                  onChanged: (value) => setState(() => _parentId = value),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
          onPressed: _busy ? null : _save,
          child: _busy
              ? const SizedBox(
                  height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
              : const Text('Create'),
        ),
      ],
    );
  }
}

/// Every account suspension has to carry a reason - it lands in the audit log.
class _ReasonDialog extends StatefulWidget {
  const _ReasonDialog({
    required this.title,
    required this.message,
    required this.actionLabel,
  });

  final String title;
  final String message;
  final String actionLabel;

  @override
  State<_ReasonDialog> createState() => _ReasonDialogState();
}

class _ReasonDialogState extends State<_ReasonDialog> {
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
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.message),
            const SizedBox(height: 16),
            TextField(
              controller: _reason,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Reason',
                helperText: 'Recorded in the audit log',
              ),
              onChanged: (_) => setState(() {}),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(minimumSize: const Size(0, 40)),
          onPressed: _reason.text.trim().length < 3
              ? null
              : () => Navigator.of(context).pop(_reason.text.trim()),
          child: Text(widget.actionLabel),
        ),
      ],
    );
  }
}
