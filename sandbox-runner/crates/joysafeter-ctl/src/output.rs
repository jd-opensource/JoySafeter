pub fn print_table(headers: &[&str], rows: &[Vec<String>]) {
    let mut widths: Vec<usize> = headers.iter().map(|h| h.len()).collect();
    for row in rows {
        for (i, cell) in row.iter().enumerate() {
            if i < widths.len() {
                widths[i] = widths[i].max(cell.len());
            }
        }
    }

    let header: String = headers
        .iter()
        .enumerate()
        .map(|(i, h)| format!("{:<width$}", h, width = widths[i] + 2))
        .collect();
    println!("{}", header);

    for row in rows {
        let line: String = row
            .iter()
            .enumerate()
            .map(|(i, cell)| {
                format!(
                    "{:<width$}",
                    cell,
                    width = widths.get(i).copied().unwrap_or(0) + 2
                )
            })
            .collect();
        println!("{}", line);
    }
}
