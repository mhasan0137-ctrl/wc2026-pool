/**
 * Auto-builds the WC 2026 Office Pool Google Form with the exact 13 questions
 * (matching predictions_template.csv / settle.py). Run once - see instructions
 * at the bottom. Creates a brand-new form, so ignore/delete the AI-suggested one.
 */
function buildPool() {
  var form = FormApp.create('WC 2026 Office Pool - Prediction Sheet')
      .setDescription('Predict 13 things for the 2026 World Cup. One entry per person. ' +
                      'Read the stats guide first: https://mhasan0137-ctrl.github.io/wc2026-pool/guide.html');

  form.addTextItem().setTitle('Your name').setRequired(true);

  form.addTextItem().setTitle('Q1. Number of letters in the longest goalscorer\'s name (first + surname; Trent Alexander-Arnold = 20)').setRequired(true);
  form.addTextItem().setTitle('Q2. Total own goals in the tournament (50 pts)').setRequired(true);
  form.addTextItem().setTitle('Q3. Total red cards (50 pts)').setRequired(true);
  form.addTextItem().setTitle('Q4. Penalty shootouts - matches decided on pens (50 pts)').setRequired(true);
  form.addTextItem().setTitle('Q5. Goals in the final, incl. shootout kicks (50 pts)').setRequired(true);

  form.addMultipleChoiceItem().setTitle('Q6. Winning continent')
      .setChoiceValues(['Europe', 'South America', 'Africa', 'Asia', 'N. America', 'Other']).setRequired(true);

  form.addListItem().setTitle('Q7. Group with the fewest total goals')
      .setChoiceValues(['Group A','Group B','Group C','Group D','Group E','Group F',
                        'Group G','Group H','Group I','Group J','Group K','Group L']).setRequired(true);

  form.addTextItem().setTitle('Q8. Youngest goalscorer age, e.g. 18y 90d (25 pts)').setRequired(true);
  form.addTextItem().setTitle('Q9. A scoreline that happens exactly once, e.g. 3-2 (reversed scores are the same)').setRequired(true);

  form.addMultipleChoiceItem().setTitle('Q10. Fastest goal - 10-second band')
      .setChoiceValues(['0-10s','10-20s','20-30s','30-40s','40-50s','50-60s','60-70s','70-80s','80-90s','90s+']).setRequired(true);

  form.addMultipleChoiceItem().setTitle('Q11. Total goals - band')
      .setChoiceValues(['<220','220-240','240-260','260-270','270-280','280-290',
                        '290-300','300-310','310-330','330-350','350+']).setRequired(true);

  form.addMultipleChoiceItem().setTitle('Q12. Most we MAKE on a single group game (net P&L)')
      .setChoiceValues(['<£25k','£25-50k','£50-75k','£75-100k','£100-150k','£150-200k','£200k+']).setRequired(true);

  form.addMultipleChoiceItem().setTitle('Q13. Most we TRADE on a single group game (turnover)')
      .setChoiceValues(['<£1m','£1-2m','£2-3m','£3-4m','£4-6m','£6-8m','£8-10m','£10-15m','£15m+']).setRequired(true);

  Logger.log('SHARE this link: ' + form.getPublishedUrl());
  Logger.log('EDIT it here:   ' + form.getEditUrl());
}

/*
HOW TO RUN
1. Go to script.google.com -> New project.
2. Delete the empty myFunction(), paste this whole file in, hit Save.
3. Pick "buildPool" in the function dropdown -> click Run.
4. Authorise it (your account -> Advanced -> Allow) the first time.
5. View -> Logs (or Execution log) to get the SHARE link and EDIT link.
6. Open the EDIT link -> Settings -> turn OFF "Collect email addresses" and
   "Limit to 1 response" so colleagues don't need to log in. Send the SHARE link.
You can ignore/delete the AI-suggested form entirely.
*/
