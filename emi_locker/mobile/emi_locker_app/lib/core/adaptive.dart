import 'package:flutter/material.dart';

/// A destination in the admin panel's side navigation.
class NavItem {
  const NavItem(this.label, this.icon, this.builder);

  final String label;
  final IconData icon;
  final WidgetBuilder builder;
}

/// Navigation that suits the window it is in.
///
/// The admin panel is used on a desktop browser, where a permanent side rail
/// beats a bottom bar, but it must still be usable on a laptop in a narrow
/// window or on a tablet. One breakpoint at 900dp: rail above, drawer below.
class AdaptiveNavScaffold extends StatefulWidget {
  const AdaptiveNavScaffold({
    super.key,
    required this.title,
    required this.subtitle,
    required this.items,
    this.actions = const [],
  });

  final String title;
  final String subtitle;
  final List<NavItem> items;
  final List<Widget> actions;

  static const wideBreakpoint = 900.0;

  @override
  State<AdaptiveNavScaffold> createState() => _AdaptiveNavScaffoldState();
}

class _AdaptiveNavScaffoldState extends State<AdaptiveNavScaffold> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= AdaptiveNavScaffold.wideBreakpoint;
    final scheme = Theme.of(context).colorScheme;
    final current = widget.items[_index];

    final body = Builder(builder: current.builder);

    if (!wide) {
      return Scaffold(
        appBar: AppBar(
          title: _Title(title: current.label, subtitle: widget.subtitle),
          actions: widget.actions,
        ),
        drawer: Drawer(
          child: SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(20),
                  child: _Title(title: widget.title, subtitle: widget.subtitle),
                ),
                const Divider(height: 1),
                Expanded(
                  child: ListView(
                    children: [
                      for (var i = 0; i < widget.items.length; i++)
                        ListTile(
                          leading: Icon(widget.items[i].icon),
                          title: Text(widget.items[i].label),
                          selected: i == _index,
                          onTap: () {
                            setState(() => _index = i);
                            Navigator.of(context).pop();
                          },
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        body: body,
      );
    }

    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            extended: MediaQuery.sizeOf(context).width >= 1200,
            minExtendedWidth: 220,
            selectedIndex: _index,
            onDestinationSelected: (i) => setState(() => _index = i),
            leading: Padding(
              padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 8),
              child: Icon(Icons.lock_clock, color: scheme.primary, size: 30),
            ),
            destinations: [
              for (final item in widget.items)
                NavigationRailDestination(
                  icon: Icon(item.icon),
                  label: Text(item.label),
                ),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: Scaffold(
              appBar: AppBar(
                title: _Title(title: current.label, subtitle: widget.subtitle),
                actions: widget.actions,
              ),
              body: body,
            ),
          ),
        ],
      ),
    );
  }
}

class _Title extends StatelessWidget {
  const _Title({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(title, style: const TextStyle(fontSize: 18)),
        Text(
          subtitle,
          style: TextStyle(
            fontSize: 12,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
  }
}

/// Keeps a wide page readable on a very wide monitor.
class PageBody extends StatelessWidget {
  const PageBody({super.key, required this.child, this.maxWidth = 1100});

  final Widget child;
  final double maxWidth;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth),
        child: child,
      ),
    );
  }
}

/// A table for admin lists.
///
/// Wrapped in a horizontal scroll view because a dense table will not fit a
/// narrow window, and silently clipping columns hides data an admin came here
/// to read.
class RecordTable extends StatelessWidget {
  const RecordTable({
    super.key,
    required this.columns,
    required this.rows,
    this.onTap,
    this.emptyMessage = 'Nothing to show',
  });

  final List<String> columns;
  final List<List<Widget>> rows;
  final void Function(int index)? onTap;
  final String emptyMessage;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Center(
            child: Text(
              emptyMessage,
              style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
          ),
        ),
      );
    }
    return Card(
      clipBehavior: Clip.antiAlias,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          columns: [
            for (final column in columns)
              DataColumn(
                label: Text(column,
                    style: const TextStyle(fontWeight: FontWeight.w700)),
              ),
          ],
          rows: [
            for (var i = 0; i < rows.length; i++)
              DataRow(
                onSelectChanged: onTap == null ? null : (_) => onTap!(i),
                cells: [for (final cell in rows[i]) DataCell(cell)],
              ),
          ],
        ),
      ),
    );
  }
}
