import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// The append-only audit trail.
///
/// There is deliberately no edit or delete here, and none exists in the API
/// either: database triggers reject any UPDATE or DELETE on this table.
class AdminAudit extends StatefulWidget {
  const AdminAudit({super.key});

  @override
  State<AdminAudit> createState() => _AdminAuditState();
}

class _AdminAuditState extends State<AdminAudit> {
  final _search = TextEditingController();
  final _viewKey = GlobalKey<AsyncViewState<Map<String, dynamic>>>();
  String _action = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
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
              Row(
                children: [
                  SizedBox(
                    width: 360,
                    child: TextField(
                      controller: _search,
                      decoration: const InputDecoration(
                        hintText: 'Filter by action, e.g. license or payment',
                        prefixIcon: Icon(Icons.search),
                      ),
                      onChanged: (value) => setState(() => _action = value),
                      onSubmitted: (_) => _viewKey.currentState?.reload(),
                    ),
                  ),
                  const SizedBox(width: 12),
                  OutlinedButton(
                    style: OutlinedButton.styleFrom(minimumSize: const Size(0, 48)),
                    onPressed: () => _viewKey.currentState?.reload(),
                    child: const Text('Apply'),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              SizedBox(
                height: MediaQuery.sizeOf(context).height * 0.7,
                child: AsyncView<Map<String, dynamic>>(
                  key: _viewKey,
                  load: () async => Map<String, dynamic>.from(
                    await session.api.get('/admin/audit',
                        query: {'action': _action, 'limit': '200'}) as Map,
                  ),
                  builder: (context, data, reload) {
                    final events = List<Map<String, dynamic>>.from(
                        (data['events'] as List)
                            .map((e) => Map<String, dynamic>.from(e as Map)));
                    return ListView(
                      children: [
                        RecordTable(
                          emptyMessage: 'No audit events match this filter',
                          columns: const [
                            'When',
                            'Action',
                            'By',
                            'Role',
                            'Entity',
                            'Id'
                          ],
                          rows: [
                            for (final event in events)
                              [
                                Text(formatDateTime(event['created_at']?.toString())),
                                Text(event['action'].toString()),
                                Text(event['actor_name']?.toString() ?? 'System'),
                                Text(event['actor_role']?.toString() ?? '-'),
                                Text(event['entity_type'].toString()),
                                Text(event['entity_id']?.toString() ?? '-'),
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
