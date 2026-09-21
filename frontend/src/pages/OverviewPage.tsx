function OverviewPage() {
    return (
        <>
            <header className="page-header">
                <div>
                    <h1>Обзор системы</h1>

                    <p>
                        Сервис прогнозирования аварийных ситуаций
                        инженерных коллекторов
                    </p>
                </div>
            </header>

            <section className="welcome-card">
                <h2>Система готова к работе</h2>

                <p>
                    Web-интерфейс подключён к backend.
                    Дальше здесь появятся сводные показатели,
                    объекты, события и прогнозы.
                </p>
            </section>
        </>
    );
}

export default OverviewPage;
