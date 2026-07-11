<?xml version="1.0" encoding="UTF-8"?>
<!--
  heat-transform.xslt — трансформация для heat.exe
  Убираает генерацию компонентов для .pyc, .pyo и прочего мусора.
-->
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:wix="http://schemas.microsoft.com/wix/2006/wi"
    xmlns="http://schemas.microsoft.com/wix/2006/wi"
    exclude-result-prefixes="wix">

  <!-- Identity copy by default -->
  <xsl:template match="@*|node()">
    <xsl:copy>
      <xsl:apply-templates select="@*|node()"/>
    </xsl:copy>
  </xsl:template>

  <!-- Skip .pyc / .pyo files -->
  <xsl:template match="wix:Component[contains(wix:File/@Source, '.pyc')]"/>
  <xsl:template match="wix:Component[contains(wix:File/@Source, '.pyo')]"/>

</xsl:stylesheet>
