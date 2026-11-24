myHouse è un plugin di modellazione architettonica che permette di modellare con semplicità un abitazione
myHouse is an architectural modeling plugin that allows for the simple modeling of a home.

Nella versione 1.0 (settaggio piani - muri - solai - porte -finestre - pilastri - tetti - travi - scale - rampe - balaustre - recinsioni)
In version 1.0, it includes settings for: floors, walls, slabs, doors, windows, columns, roofs, beams, stairs, ramps, balustrades, and fences.

Il plugin è stato inserito tra le estensioni ufficiale quindi potrà essere anche scaricato direttamente dalle estensioni del programma oppure lo puoi scaricare qui sotto, se scaricandolo dalle estensioni vedi che la versione non è stata ancora aggiornata scaricalo da qui in quanto il caricamento nelle estensioni ufficiali avviene dopo qualche giorno

The plugin has been added to the official extensions, so it can be downloaded directly via the program's extensions menu; alternatively, you can download it below. If you find that the version in the official extensions hasn't been updated yet, please download it from here, as it can take a few days for updates to appear in the official extensions list.

## Aggiunte di questo ramo (su myHouse 1.4)

Il codice sorgente della 1.4 è nella cartella `myhouse/`; `myhouse.zip` contiene gli stessi file, con le aggiunte qui sotto. Le traduzioni seguono lo schema della 1.4 (testi in italiano, inglese in `_traduzioni_en.py`).

**Unità**

- Misure in piedi e pollici oppure metriche: Estensioni > myHouse > Unità… (segui il documento, piedi e pollici, metrico). In piedi e pollici i campi con "(m)" si leggono e si scrivono in piedi e pollici (96, 8', 8'6 1/2", 7 4) e le misure proposte sono quelle americane; il modello resta in metri. In metrico non cambia nulla.

**Muri**

- Ortogonale a passi di 45°.
- Adotta muro: trasforma un gruppo esistente a forma di parallelepipedo in un muro myHouse, così porte e finestre lo possono forare.
- Allunga muro: sposta un'estremità con un clic o digitando la lunghezza; gli angoli collegati la seguono.
- Dividi muro: taglia un muro in due nel punto del clic.
- Giunto tra muri: angolo a sghembo oppure di testa, con l'uno o l'altro muro passante.

**Tetti**

- Tetto automatico: dopo il contorno premi P e indica la pendenza (8/12, 30° o 58%); colmi, displuvi e compluvi sono calcolati per qualsiasi contorno, anche con rientranze e sporgenze.
- Clic su un lato del contorno per farne un timpano; un altro clic lo riporta a falda.
- W prende il contorno dal filo esterno dei muri.

**Porte**

- Larghezza e altezza della porta vera e propria (l'anta), accanto a quelle totali: il telaio sta all'esterno. In piedi e pollici le misure totali sono calcolate dalla porta e dal telaio.
- Porte a libro per armadi, singole o doppie.
- Ribalta la porta (lato della maniglia): tasto destro su una porta posata, oppure R durante la posa.

**Finestre**

- Finestre accoppiate: montante fisso a "I" tra un'anta e l'altra; anima, alette e profondità del canale si impostano separatamente.
- Misure standard americane per tipo di finestra (solo in piedi e pollici); si può sempre digitare una misura qualsiasi.

**Porte e finestre**

- Durante la posa, Spazio passa da spigolo sinistro a centro a spigolo destro.

## What this branch adds (on top of myHouse 1.4)

The 1.4 source code is in the `myhouse/` folder; `myhouse.zip` holds the same files, with the additions below. Translations follow 1.4's scheme (Italian in the code, English in `_traduzioni_en.py`).

**Units**

- Sizes in feet and inches or metric: Extensions > myHouse > Units… (follow the document, feet and inches, metric). In feet and inches the fields marked "(m)" are read and typed in feet and inches (96, 8', 8'6 1/2", 7 4) and the proposed sizes are US ones; the model is still stored in metres. Nothing changes in metric.

**Walls**

- Ortho in 45° steps.
- Adopt wall: turns an existing box-shaped group into a myHouse wall, so doors and windows can cut it.
- Stretch wall: moves one end by click or typed length; joined corners follow.
- Split wall: cuts a wall in two at the clicked point.
- Wall joint: mitred or butt corner, with either wall running through.

**Roofs**

- Automatic roof: after the outline press P and give the pitch (8/12, 30° or 58%); ridges, hips and valleys are worked out for any outline, bump-outs and recesses included.
- Click an edge of the outline to make it a gable end; click again for a sloping plane.
- W takes the outline from the outer face of the walls.

**Doors**

- Width and height of the door itself (the slab), beside the total ones: the frame sits outside. In feet and inches the totals are worked out from the door and the frame.
- Bi-fold closet doors, single or dual.
- Reverse door (handle side): right-click a placed door, or R while placing.

**Windows**

- Mulled windows: a fixed I-shaped mullion between one sash and the next; web, flanges and channel depth are set independently.
- US standard sizes by window type (feet and inches only); any size can still be typed.

**Doors and windows**

- While placing, Space goes from left edge to middle to right edge.
