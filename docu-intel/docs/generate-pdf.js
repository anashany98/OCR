const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const htmlPath = path.join(__dirname, 'informe-docuintel.html');
  const pdfPath = path.join(__dirname, 'Docu-Intel_Informe_Tecnico_Comercial.pdf');

  console.log('Abriendo navegador...');
  const browser = await chromium.launch();
  const page = await browser.newPage();

  console.log('Cargando HTML...');
  await page.goto('file:///' + htmlPath.replace(/\\/g, '/'), { waitUntil: 'networkidle' });

  console.log('Generando PDF...');
  await page.pdf({
    path: pdfPath,
    format: 'A4',
    margin: { top: '20mm', bottom: '20mm', left: '18mm', right: '18mm' },
    printBackground: true,
    displayHeaderFooter: false,
  });

  await browser.close();
  console.log('PDF generado: ' + pdfPath);
})();
