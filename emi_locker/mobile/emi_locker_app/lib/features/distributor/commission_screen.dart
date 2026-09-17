import 'package:flutter/material.dart';

import '../../core/money.dart';
import '../../core/widgets.dart';
import '../../main.dart';

/// Commission earned, under the rates head office has configured.
///
/// When no rate is set the screen says so rather than showing a confident
/// zero, because those are different facts: "you earned nothing" and "nobody
/// has agreed what you earn yet".
class CommissionScreen extends StatelessWidget {
  const CommissionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return AsyncView<Map<String, dynamic>>(
      load: () async => Map<String, dynamic>.from(
          await session.api.get('/distributor/commission') as Map),
      builder: (context, data, reload) {
        final rules = Map<String, dynamic>.from(data['rules'] as Map);
        final rows = List<Map<String, dynamic>>.from(
            (data['rows'] as List).map((e) => Map<String, dynamic>.from(e as Map)));
        final configured = rules['configured'] as bool;
        final scheme = Theme.of(context).colorScheme;

        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (!configured)
              Card(
                color: scheme.tertiaryContainer,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      Icon(Icons.info_outline, color: scheme.onTertiaryContainer),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          'No commission rate has been set yet. Head office '
                          'configures the rates, and this page will show what '
                          'you have earned once they do.',
                          style: TextStyle(color: scheme.onTertiaryContainer),
                        ),
                      ),
                    ],
                  ),
                ),
              )
            else
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Earned across the network',
                          style: Theme.of(context).textTheme.labelLarge?.copyWith(
                                color: scheme.onSurfaceVariant,
                              )),
                      const SizedBox(height: 6),
                      MoneyText(data['total_paise'] as int, emphasise: true),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 20),
            Text('Current rates', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Column(
                  children: [
                    LabelledRow(
                      'Distributor, per activation',
                      Money.format(rules['distributor_per_activation_paise'] as int),
                    ),
                    LabelledRow(
                      'Retailer, per activation',
                      Money.format(rules['retailer_per_activation_paise'] as int),
                    ),
                    LabelledRow(
                      'Distributor, share of financed amount',
                      '${(rules['distributor_percent_of_financed_bp'] as int) / 100}%',
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),
            Text('By account', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            Card(
              child: Column(
                children: [
                  for (var i = 0; i < rows.length; i++) ...[
                    if (i > 0) const Divider(height: 1),
                    ListTile(
                      title: Text(rows[i]['name'].toString(),
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                      subtitle: Text(
                        '${rows[i]['role'] == 'DISTRIBUTOR' ? 'Distributor' : 'Retailer'}'
                        ' • ${rows[i]['activations']} activations',
                      ),
                      trailing: Text(
                        Money.format(rows[i]['commission_paise'] as int),
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 32),
          ],
        );
      },
    );
  }
}
