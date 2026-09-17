import 'package:flutter/material.dart';

import '../../core/adaptive.dart';
import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';
import '../customer/finance_detail.dart';

const financeStatuses = ['', 'ACTIVE', 'OVERDUE', 'COMPLETED', 'CANCELLED'];

class AdminFinances extends StatefulWidget {
  const AdminFinances({super.key});

  @override
  State<AdminFinances> createState() => _AdminFinancesState();
}

class _AdminFinancesState extends State<AdminFinances> {
  final _viewKey = GlobalKey<AsyncViewState<Map<String, dynamic>>>();
  String _status = '';

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
              StatusFilter(
                statuses: financeStatuses,
                selected: _status,
                onChanged: (value) {
                  setState(() => _status = value);
                  _viewKey.currentState?.reload();
                },
              ),
              const SizedBox(height: 16),
              SizedBox(
                height: MediaQuery.sizeOf(context).height * 0.72,
                child: AsyncView<Map<String, dynamic>>(
                  key: _viewKey,
                  load: () async => Map<String, dynamic>.from(
                    await session.api
                        .get('/admin/finances', query: {'status': _status}) as Map,
                  ),
                  builder: (context, data, reload) {
                    final finances = List<Map<String, dynamic>>.from(
                        (data['finances'] as List)
                            .map((e) => Map<String, dynamic>.from(e as Map)));
                    return ListView(
                      children: [
                        RecordTable(
                          emptyMessage: 'No finance accounts match this filter',
                          columns: const [
                            'Finance',
                            'Customer',
                            'Retailer',
                            'IMEI',
                            'Financed',
                            'EMI',
                            'Outstanding',
                            'Status'
                          ],
                          onTap: (index) => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => FinanceDetailScreen(
                                financeId: finances[index]['id'].toString(),
                                allowPay: false,
                              ),
                            ),
                          ),
                          rows: [
                            for (final finance in finances)
                              [
                                Text(finance['id'].toString()),
                                Text(finance['customer_name'].toString()),
                                Text(finance['retailer_name'].toString()),
                                Text(finance['imei']?.toString() ?? '-'),
                                Text(Money.format(finance['principal'] as int)),
                                Text(Money.format(finance['emi_amount'] as int)),
                                Text(Money.format(
                                    finance['outstanding_paise'] as int)),
                                StatusChip(status: finance['status'].toString()),
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

/// A row of filter chips, with the blank option meaning "everything".
class StatusFilter extends StatelessWidget {
  const StatusFilter({
    super.key,
    required this.statuses,
    required this.selected,
    required this.onChanged,
  });

  final List<String> statuses;
  final String selected;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final status in statuses)
          ChoiceChip(
            label: Text(status.isEmpty ? 'All' : prettyStatusLabel(status)),
            selected: selected == status,
            onSelected: (_) => onChanged(status),
          ),
      ],
    );
  }
}

String prettyStatusLabel(String status) => status
    .split('_')
    .map((w) => w.isEmpty ? w : w[0] + w.substring(1).toLowerCase())
    .join(' ');
