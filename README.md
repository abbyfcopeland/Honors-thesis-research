# Honors-thesis-research
Analyzing how American think tanks across the ideological spectrum frame racial inequality and attribute causes of racial disparities. Honors thesis, Stanford University, 2026.
# Overview
This project examines whether and how American think tanks differ in the way they frame and explain racial disparities. Using a corpus of 2,337 articles from four prominent think tanks spanning the ideological spectrum — the Southern Poverty Law Center (SPLC), the Brookings Institution, the Cato Institute, and the Heritage Foundation — this study investigates whether political ideology predicts (1) how often think tanks mention racial disparities and (2) what types of causal attributions they offer: individualistic or structural.
Articles were collected via custom Python web scrapers and classified using a two-stage few-shot LLM annotation pipeline (GPT-4.1-mini), validated against a human-coded ground truth set. Key findings show that ideology more consistently predicts how think tanks explain racial disparities than whether they mention them, with structural attribution rates following a clear ideological gradient.

# Methods Summary
Data collection: Custom Python scrapers queried each think tank's website using 13 search terms related to racial disparities. Articles were extracted with title, author(s), body text, and publication date.
Corpus: 2,337 articles published between October 2016 and October 2025 from SPLC, Brookings, Cato, and Heritage.
Annotation: Two-stage few-shot LLM classification using GPT-4.1-mini, validated against 127 human-coded articles. Stage 1 coded disparity mentions; Stage 2 coded individual and structural attributions.
Analysis: Binary and ordinal logistic regressions predicting disparity mention, attribution type, and overall engagement from think tank ideology (coded as a continuous ordinal variable).

# Authors
Abby Copeland
B.A. Psychology, Stanford University, 2026
abbyfc@stanford.edu

# Advisors 
Anmol Gupta 
Ph.D Canidate in Psychology, Stanford University

Jordan Starck, Ph.D
Assistant Professor of Psychology, Stanford University

