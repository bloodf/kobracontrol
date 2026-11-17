// PrimeVue's own labels (select filter, empty lists, the dialog's close button) in the languages the shared foundation
// has none for. The same keys as the foundation's pt-BR set, minus the calendar's: this page has no date picker.
import type { Locale } from './i18n-core';

type PrimeLabels = Record<string, string | string[] | Record<string, string>>;

export const PRIME_LOCALE: Record<Exclude<Locale, 'en' | 'pt-BR'>, PrimeLabels> = {
  es: {
    accept: 'Confirmar', reject: 'Volver', choose: 'Seleccionar', upload: 'Enviar', cancel: 'Cancelar',
    emptyMessage: 'No hay elementos', emptyFilterMessage: 'Ningún resultado con estos filtros',
    emptySearchMessage: 'No se encontraron resultados', searchMessage: '{0} resultados encontrados',
    selectionMessage: '{0} elementos seleccionados', emptySelectionMessage: 'Ningún elemento seleccionado',
    aria: { close: 'Cerrar', previous: 'Anterior', next: 'Siguiente', firstPageLabel: 'Primera página', lastPageLabel: 'Última página',
      nextPageLabel: 'Página siguiente', prevPageLabel: 'Página anterior', selectRow: 'Seleccionar fila', unselectRow: 'Deseleccionar fila' },
  },
  de: {
    accept: 'Bestätigen', reject: 'Zurück', choose: 'Auswählen', upload: 'Senden', cancel: 'Abbrechen',
    emptyMessage: 'Keine Einträge', emptyFilterMessage: 'Keine Ergebnisse für diese Filter',
    emptySearchMessage: 'Keine Ergebnisse gefunden', searchMessage: '{0} Ergebnisse gefunden',
    selectionMessage: '{0} Einträge ausgewählt', emptySelectionMessage: 'Kein Eintrag ausgewählt',
    aria: { close: 'Schließen', previous: 'Zurück', next: 'Weiter', firstPageLabel: 'Erste Seite', lastPageLabel: 'Letzte Seite',
      nextPageLabel: 'Nächste Seite', prevPageLabel: 'Vorherige Seite', selectRow: 'Zeile auswählen', unselectRow: 'Zeilenauswahl aufheben' },
  },
  'zh-CN': {
    accept: '确定', reject: '返回', choose: '选择', upload: '发送', cancel: '取消',
    emptyMessage: '没有项目', emptyFilterMessage: '没有符合筛选条件的结果',
    emptySearchMessage: '未找到结果', searchMessage: '找到 {0} 个结果',
    selectionMessage: '已选择 {0} 项', emptySelectionMessage: '未选择任何项目',
    aria: { close: '关闭', previous: '上一个', next: '下一个', firstPageLabel: '第一页', lastPageLabel: '最后一页',
      nextPageLabel: '下一页', prevPageLabel: '上一页', selectRow: '选择行', unselectRow: '取消选择行' },
  },
  pl: {
    accept: 'Potwierdź', reject: 'Wróć', choose: 'Wybierz', upload: 'Wyślij', cancel: 'Anuluj',
    emptyMessage: 'Brak elementów', emptyFilterMessage: 'Brak wyników dla tych filtrów',
    emptySearchMessage: 'Nie znaleziono wyników', searchMessage: 'Znalezione wyniki: {0}',
    selectionMessage: 'Zaznaczone elementy: {0}', emptySelectionMessage: 'Nie zaznaczono żadnego elementu',
    aria: { close: 'Zamknij', previous: 'Poprzedni', next: 'Następny', firstPageLabel: 'Pierwsza strona', lastPageLabel: 'Ostatnia strona',
      nextPageLabel: 'Następna strona', prevPageLabel: 'Poprzednia strona', selectRow: 'Zaznacz wiersz', unselectRow: 'Odznacz wiersz' },
  },
};
